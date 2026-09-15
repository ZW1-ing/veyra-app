import asyncio
from collections.abc import Sequence

from app.agent.swarm import (
    PlanTask,
    TaskResult,
    build_member_prompt,
    build_summary_prompt,
    parse_plan,
    run_members,
)
from app.core.config import Settings
from app.llm.base import ChatChunk, ChatMessage, Usage
from tests.conftest import parse_sse

VALID_PLAN = """
```json
{"tasks": [
  {"id": "t1", "title": "调研员", "task": "查清楚工具调用步数上限", "depends_on": []},
  {"id": "t2", "title": "校验员", "task": "复核 t1 的结论", "depends_on": ["t1"]}
]}
```
"""


def test_parse_plan_reads_fenced_json_and_keeps_dependencies():
    tasks, note = parse_plan(VALID_PLAN, "问题", max_members=5)
    assert note is None
    assert [t.id for t in tasks] == ["t1", "t2"]
    assert tasks[1].depends_on == ["t1"]
    assert tasks[0].title == "调研员"


def test_parse_plan_falls_back_when_json_is_broken():
    tasks, note = parse_plan("我觉得可以分成几步，但是我不想写 JSON", "原始问题", max_members=5)
    assert len(tasks) == 1
    assert tasks[0].task == "原始问题"
    assert note and "降级" in note


def test_parse_plan_rejects_cycle_and_unknown_dependency():
    forward_ref = '{"tasks": [{"id": "t2", "task": "写结论", "depends_on": ["t1"]}, {"id": "t1", "task": "查资料", "depends_on": []}, {"id": "t3", "task": "兜底", "depends_on": ["t9"]}]}'
    # 依赖写在前面的任务也要保留；指向不存在任务的依赖才被丢掉
    tasks, _ = parse_plan(forward_ref, "问题", max_members=5)
    assert {t.id for t in tasks} == {"t1", "t2", "t3"}
    assert next(t for t in tasks if t.id == "t2").depends_on == ["t1"]
    assert next(t for t in tasks if t.id == "t3").depends_on == []


def test_parse_plan_detects_real_cycle_and_falls_back():
    real_cycle = '{"tasks": [{"id": "t1", "task": "a", "depends_on": ["t2"]}, {"id": "t2", "task": "b", "depends_on": ["t1"]}]}'
    tasks, note = parse_plan(real_cycle, "原始问题", max_members=5)
    assert len(tasks) == 1 and tasks[0].task == "原始问题"
    assert note and "循环依赖" in note


def test_parse_plan_truncates_to_member_limit():
    raw = '{"tasks": [' + ",".join(
        f'{{"id": "t{i}", "task": "任务{i}", "depends_on": []}}' for i in range(1, 9)
    ) + "]}"
    tasks, note = parse_plan(raw, "问题", max_members=3)
    assert len(tasks) == 3
    assert note and "上限" in note


def test_member_prompt_injects_upstream_output():
    task = PlanTask(id="t2", title="写手", task="写结论", depends_on=["t1"])
    upstream = [TaskResult(id="t1", title="调研员", ok=True, output="结论是八步")]
    messages = build_member_prompt("总问题", task, upstream)
    user_content = messages[-1].content
    assert "结论是八步" in user_content
    assert "调研员" in user_content


def test_summary_prompt_only_asks_for_citations_when_sources_exist():
    results = [TaskResult(id="t1", title="调研员", ok=True, output="说了一些东西")]

    without = build_summary_prompt("问题", results, knowledge="")
    assert "[S1]" not in without[-1].content

    with_sources = build_summary_prompt("问题", results, knowledge="[S1] 来源：doc.md｜片段内容")
    assert "[S1]" in with_sources[-1].content


class RecordingProvider:
    """记录并发峰值、按提示词内容分派回答的假模型。"""

    name = "recording"
    model = "recording"

    def __init__(self, delay: float = 0.05, fail_titles: Sequence[str] = ()):
        self.delay = delay
        self.fail_titles = set(fail_titles)
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        content = messages[-1].content
        self.calls.append(content)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            for title in self.fail_titles:
                if f"你是「{title}」" in messages[0].content:
                    raise RuntimeError("模拟成员失败")
            for title in ("调研员", "写手", "校验员"):
                if f"你是「{title}」" in messages[0].content:
                    return f"{title}的产出", Usage(10, 5)
            return "兜底产出", Usage(10, 5)
        finally:
            self.active -= 1

    async def stream(self, messages: Sequence[ChatMessage]):
        yield ChatChunk(delta="汇总：")
        yield ChatChunk(delta="最终答复")
        yield ChatChunk(usage=Usage(20, 10))


async def test_run_members_respects_dependencies_and_concurrency():
    tasks = [
        PlanTask("t1", "调研员", "查资料"),
        PlanTask("t2", "写手", "写初稿"),
        PlanTask("t3", "校验员", "复核", depends_on=["t1", "t2"]),
    ]
    provider = RecordingProvider()
    settings = Settings(database_url="sqlite://", swarm_max_concurrency=2)

    events = [event async for event in run_members(provider, "问题", tasks, "", settings)]
    statuses = {(e.get("id"), e.get("status")) for e in events if e["type"] == "member"}

    assert ("t3", "running") in statuses
    assert provider.max_active <= 2, "并发不能超过配置上限"
    # t3 必须在 t1、t2 之后才开始：它的 running 事件晚于两者的 done
    order = [e["id"] for e in events if e["type"] == "member" and e["status"] == "done"]
    running = [e["id"] for e in events if e["type"] == "member" and e["status"] == "running"]
    assert running.index("t3") > order.index("t1")
    assert running.index("t3") > order.index("t2")


async def test_run_members_skips_dependents_when_upstream_fails():
    tasks = [
        PlanTask("t1", "调研员", "查资料"),
        PlanTask("t2", "写手", "写初稿", depends_on=["t1"]),
    ]
    provider = RecordingProvider(fail_titles=["调研员"])
    settings = Settings(database_url="sqlite://", swarm_max_concurrency=2)

    events = [event async for event in run_members(provider, "问题", tasks, "", settings)]
    done = [e for e in events if e["type"] == "member" and e["status"] == "failed"]
    skipped = [e for e in events if e["type"] == "member" and e["status"] == "skipped"]

    assert done and done[0]["id"] == "t1"
    assert skipped and skipped[0]["id"] == "t2"
    assert "失败" in skipped[0]["detail"]


class PlanThenAnswerProvider:
    """规划阶段返回固定计划，成员阶段按角色回答，汇总阶段流式输出。"""

    name = "scripted"
    model = "scripted"

    def __init__(self, plan_json: str):
        self.plan_json = plan_json

    async def complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        if "任务规划器" in messages[-1].content:
            return self.plan_json, Usage(30, 20)
        for title in ("调研员", "校验员"):
            if f"你是「{title}」" in messages[0].content:
                return f"{title}认为上限是八步。", Usage(12, 6)
        return "成员产出", Usage(12, 6)

    async def stream(self, messages: Sequence[ChatMessage]):
        assert "成员产出" in messages[-1].content or "调研员" in messages[-1].content
        yield ChatChunk(delta="综合两位成员的意见，")
        yield ChatChunk(delta="工具调用上限是八步。[S1]")
        yield ChatChunk(usage=Usage(40, 18))


def test_swarm_endpoint_runs_full_flow(client, app_instance):
    app_instance.state.provider = PlanThenAnswerProvider(VALID_PLAN)

    response = client.post(
        "/chat",
        json={"message": "Veyra 的工具调用上限是几步？", "mode": "swarm", "use_knowledge": False},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["mode"] == "swarm"
    assert "八步" in body["text"]
    assert {m["id"] for m in body["members"]} == {"t1", "t2"}
    assert all(m["ok"] for m in body["members"])
    assert body["usage"]["completion_tokens"] > 0


def test_swarm_stream_emits_plan_and_member_events(client, app_instance):
    app_instance.state.provider = PlanThenAnswerProvider(VALID_PLAN)

    response = client.post(
        "/chat/stream",
        json={"message": "工具调用上限？", "mode": "swarm", "use_knowledge": False},
    )
    events = parse_sse(response.text)
    types = [e["type"] for e in events]

    assert "plan" in types
    assert types.count("member") >= 3  # 两个成员各有 running + done
    assert types[-1] == "done"
    final = next(e for e in events if e["type"] == "final")
    assert final["mode"] == "swarm"
    assert final["members"]


def test_session_remembers_mode(client, app_instance):
    app_instance.state.provider = PlanThenAnswerProvider(VALID_PLAN)

    first = client.post("/chat", json={"message": "第一次", "mode": "swarm"}).json()
    # 第二次不传 mode，应该沿用会话里记住的 swarm
    second = client.post("/chat", json={"session_id": first["session_id"], "message": "第二次"}).json()
    assert second["mode"] == "swarm"
    assert second["members"]
