"""多智能体协作：Leader 规划 → 依赖感知调度 → 汇总。

和单智能体的区别在于「先把任务拆开」：Leader 只负责拆解和分工，
成员各自独立作答，最后 Leader 基于成员产出写终稿。

三件容易做错的事，这里都显式处理了：
1. 模型给的计划不可信 —— 要校验 id 唯一、依赖存在、无环、成员数上限，解析失败就降级成单任务。
2. 成员不能无限并发 —— 用信号量限制，本地模型并发太高只会互相抢显存。
3. 一个成员失败不能拖垮整场 —— 依赖失败的下游任务标记跳过，其余照常汇总。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from ..core.config import Settings
from ..llm.base import ChatMessage, Usage


@dataclass
class PlanTask:
    id: str
    title: str
    task: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    id: str
    title: str
    ok: bool
    output: str = ""
    error: str = ""


def build_plan_prompt(question: str, max_members: int, persona: str | None = None) -> str:
    persona_block = f"\n角色设定（优先遵循）：{persona.strip()}\n" if persona and persona.strip() else ""

    return f"""你是任务规划器。把下面的任务拆成最多 {max_members} 个可由不同角色独立完成的子任务。
{persona_block}

只输出 JSON，不要输出任何其他文字，格式：
{{"tasks": [
  {{"id": "t1", "title": "成员角色", "task": "要做什么", "depends_on": []}},
  {{"id": "t2", "title": "成员角色", "task": "要做什么", "depends_on": ["t1"]}}
]}}

要求：
1. id 用 t1、t2 这种简短标识，depends_on 里只能引用前面出现过的 id。
2. 能并行的任务不要互相依赖，确实需要前一步产出的才写 depends_on。
3. 如果任务本身很简单，只给一个子任务。

用户任务：{question}"""


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON 对象，容忍 ```json 包裹和前后废话。"""
    if not text:
        return None
    candidates: list[str] = []
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in reversed(candidates):
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def parse_plan(text: str, question: str, max_members: int = 5) -> tuple[list[PlanTask], str | None]:
    """解析计划。返回 (任务列表, 降级说明)。降级时用单任务兜底，永远返回可用计划。"""
    fallback = [PlanTask(id="t1", title="助手", task=question)]
    payload = _extract_json(text)
    if not payload or not isinstance(payload.get("tasks"), list):
        return fallback, "计划解析失败，已降级为单任务执行"

    # 两阶段解析：
    # 第一阶段只收 id 和内容，保留原始依赖；
    # 第二阶段再过滤依赖、查环。这样「依赖后面才出现的任务」这种正常写法不会被误删，
    # 环检测也才有意义（一阶段就过滤的话，环永远不可能出现）。
    raw_tasks: list[PlanTask] = []
    seen: set[str] = set()
    for raw in payload["tasks"]:
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("id") or "").strip()
        task_text = str(raw.get("task") or "").strip()
        if not task_id or not task_text or task_id in seen:
            continue
        depends = raw.get("depends_on")
        depends = [str(d) for d in depends] if isinstance(depends, list) else []
        raw_tasks.append(
            PlanTask(
                id=task_id,
                title=str(raw.get("title") or task_id).strip(),
                task=task_text,
                depends_on=depends,
            )
        )
        seen.add(task_id)

    if not raw_tasks:
        return fallback, "计划里没有有效任务，已降级为单任务执行"

    tasks = [
        PlanTask(
            id=task.id,
            title=task.title,
            task=task.task,
            # 过滤掉指向不存在任务的依赖；不要求被依赖的任务在前面出现过
            depends_on=list(dict.fromkeys(d for d in task.depends_on if d in seen and d != task.id)),
        )
        for task in raw_tasks
    ]

    notes: list[str] = []
    if len(tasks) > max_members:
        notes.append(f"成员数超过上限，已截断为 {max_members} 个")
        tasks = tasks[:max_members]
        valid = {t.id for t in tasks}
        for task in tasks:
            task.depends_on = [d for d in task.depends_on if d in valid]

    if _has_cycle(tasks):
        return fallback, "计划存在循环依赖，已降级为单任务执行"

    return tasks, ("；".join(notes) if notes else None)


def _has_cycle(tasks: Sequence[PlanTask]) -> bool:
    graph = {t.id: list(t.depends_on) for t in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.discard(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def build_member_prompt(
    question: str,
    task: PlanTask,
    upstream: Sequence[TaskResult],
    knowledge: str = "",
    persona: str | None = None,
) -> list[ChatMessage]:
    context_parts = [f"整体任务：{question}", f"你负责的子任务：{task.task}"]
    if persona and persona.strip():
        context_parts.append(f"角色设定（优先遵循）：{persona.strip()}")
    if upstream:
        context_parts.append("其他成员的产出（供参考，不要重复他们的工作）：")
        context_parts.extend(f"【{item.title}】{item.output}" for item in upstream)
    if knowledge:
        context_parts.append(knowledge)
    context_parts.append("直接给结论，控制在 200 字以内，不要复述任务。")
    return [
        ChatMessage(role="system", content=f"你是「{task.title}」，专注于自己那部分工作。"),
        ChatMessage(role="user", content="\n".join(context_parts)),
    ]


async def run_members(
    provider,
    question: str,
    tasks: Sequence[PlanTask],
    knowledge: str,
    settings: Settings,
    persona: str | None = None,
) -> AsyncIterator[dict]:
    """依赖感知调度：就绪的任务并发跑，完成的产出注入下游。

    产出事件：member（running/done/failed/skipped）。
    """
    results: dict[str, TaskResult] = {}
    pending = {task.id: task for task in tasks}
    semaphore = asyncio.Semaphore(max(1, settings.swarm_max_concurrency))

    async def run_one(task: PlanTask) -> TaskResult:
        upstream = [results[dep] for dep in task.depends_on if dep in results]
        messages = build_member_prompt(question, task, upstream, knowledge, persona)
        async with semaphore:
            try:
                text, _usage = await asyncio.wait_for(
                    provider.complete(messages),
                    timeout=settings.swarm_task_timeout_seconds,
                )
                return TaskResult(task.id, task.title, True, output=text.strip())
            except TimeoutError:
                return TaskResult(task.id, task.title, False, error="执行超时")
            except Exception as exc:  # noqa: BLE001 单个成员失败不能拖垮整场
                return TaskResult(task.id, task.title, False, error=f"{type(exc).__name__}: {exc}")

    while pending:
        ready = [
            task
            for task in pending.values()
            if all(dep in results for dep in task.depends_on)
        ]
        if not ready:
            # 剩下的任务依赖永远无法满足（理论上被 parse_plan 挡住了，这里是兜底）
            for task in pending.values():
                results[task.id] = TaskResult(task.id, task.title, False, error="依赖无法满足")
                yield {
                    "type": "member",
                    "id": task.id,
                    "title": task.title,
                    "status": "skipped",
                    "detail": "依赖无法满足",
                }
            break

        runnable: list[PlanTask] = []
        for task in ready:
            failed = next((d for d in task.depends_on if not results[d].ok), None)
            if failed:
                results[task.id] = TaskResult(
                    task.id, task.title, False, error=f"前置任务 {failed} 失败，已跳过"
                )
                pending.pop(task.id)
                yield {
                    "type": "member",
                    "id": task.id,
                    "title": task.title,
                    "status": "skipped",
                    "detail": f"前置任务 {failed} 失败",
                }
            else:
                runnable.append(task)

        if not runnable:
            continue

        for task in runnable:
            yield {"type": "member", "id": task.id, "title": task.title, "status": "running"}

        coroutines = [run_one(task) for task in runnable]
        for completed in asyncio.as_completed(coroutines):
            result = await completed
            results[result.id] = result
            pending.pop(result.id, None)
            yield {
                "type": "member",
                "id": result.id,
                "title": result.title,
                "status": "done" if result.ok else "failed",
                "detail": (result.output or result.error)[:200],
            }

    # 把结果挂回调用方（通过最后一个事件带出去，避免额外返回值）
    yield {"type": "members_done", "results": [r.__dict__ for r in results.values()]}


def build_summary_prompt(
    question: str,
    results: Sequence[TaskResult],
    knowledge: str = "",
    persona: str | None = None,
) -> list[ChatMessage]:
    parts = [f"用户任务：{question}", "各成员产出："]
    if persona and persona.strip():
        parts.insert(1, f"角色设定（优先遵循）：{persona.strip()}")
    for item in results:
        body = item.output if item.ok else f"（该成员失败：{item.error}）"
        parts.append(f"【{item.title}】{body}")
    if knowledge:
        parts.append(knowledge)
    instruction = "请综合上述产出，给出一个完整、连贯的最终回答。"
    if knowledge:
        # 只有真的给了资料才要求标注来源：否则模型会凭空编出 [S2]、[S5] 这类编号
        instruction += "引用上面提供的资料片段时，直接写 [S1] 这样的编号，没有依据不要编造来源。"
    instruction += "失败的部分如果影响结论，要明确说明。"
    parts.append(instruction)
    return [
        ChatMessage(role="system", content="你是团队负责人，负责把成员产出汇总成最终答复。"),
        ChatMessage(role="user", content="\n".join(parts)),
    ]


async def stream_swarm(
    provider,
    question: str,
    knowledge: str,
    settings: Settings,
    system_prompt: str | None = None,
) -> AsyncIterator[dict]:
    """完整流程：规划 → 执行成员 → 汇总，逐段产出事件。"""
    plan_text, plan_usage = await provider.complete(
        [
            ChatMessage(
                role="user",
                content=build_plan_prompt(question, settings.swarm_max_members, system_prompt),
            )
        ]
    )
    tasks, note = parse_plan(plan_text, question, settings.swarm_max_members)

    yield {
        "type": "plan",
        "tasks": [task.__dict__ for task in tasks],
        "note": note,
    }

    usage = Usage(plan_usage.prompt_tokens, plan_usage.completion_tokens)
    results: list[TaskResult] = []
    async for event in run_members(provider, question, tasks, knowledge, settings, system_prompt):
        if event["type"] == "members_done":
            results = [TaskResult(**item) for item in event["results"]]
            continue
        yield event

    collected: list[str] = []
    async for chunk in provider.stream(
        build_summary_prompt(question, results, knowledge, system_prompt)
    ):
        if chunk.delta:
            collected.append(chunk.delta)
            yield {"type": "token", "text": chunk.delta}
        if chunk.usage:
            usage.prompt_tokens += chunk.usage.prompt_tokens
            usage.completion_tokens += chunk.usage.completion_tokens

    yield {
        "type": "final",
        "text": "".join(collected),
        "steps": len([r for r in results if r.ok]),
        "members": [r.__dict__ for r in results],
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        },
    }
