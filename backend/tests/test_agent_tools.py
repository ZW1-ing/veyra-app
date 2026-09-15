import pytest

from app.agent.prompts import extract_action
from app.agent.tools import build_default_registry, tool_calc
from app.llm.mock import MockProvider
from tests.conftest import parse_sse


def test_calc_tool_computes_and_rejects_bad_input():
    assert tool_calc("(23+47)*2") == "140"
    assert tool_calc("7/2") == "3.5"
    with pytest.raises(ValueError):
        tool_calc("__import__('os').system('dir')")


def test_registry_handles_unknown_tool_and_bad_args():
    registry = build_default_registry()
    ok, message = registry.run("not-exist", {})
    assert ok is False and "不存在" in message
    ok, message = registry.run("calc", {"wrong": 1})
    assert ok is False and "参数不匹配" in message


def test_extract_action_accepts_fenced_and_plain_json():
    fenced = '```json\n{"tool": "calc", "args": {"expression": "1+1"}}\n```'
    assert extract_action(fenced) == {"tool": "calc", "args": {"expression": "1+1"}}
    plain = '{"tool": "now", "args": {}}'
    assert extract_action(plain)["tool"] == "now"
    assert extract_action("就是一句普通回答") is None


def test_agent_calls_tool_then_answers(client, app_instance):
    """第一轮让模型要求调用 calc，第二轮给最终答案。"""
    app_instance.state.provider = MockProvider(
        [
            '{"tool": "calc", "args": {"expression": "23*47"}}',
            "23 乘 47 等于 1081。",
        ]
    )

    response = client.post("/chat", json={"message": "23*47 等于多少？", "use_knowledge": False})
    assert response.status_code == 200
    body = response.json()
    assert body["tool_calls"] == ["calc"]
    assert body["steps"] == 1
    assert "1081" in body["text"]


def test_agent_stops_at_step_limit(client, app_instance):
    """模型一直要求调用工具时，必须在步数上限处收住，不能无限循环。"""
    app_instance.state.provider = MockProvider(
        ['{"tool": "now", "args": {}}'] * 10
    )
    response = client.post(
        "/chat/stream",
        json={"message": "现在几点", "use_knowledge": False, "max_steps": 2},
    )
    events = parse_sse(response.text)
    tool_events = [e for e in events if e["type"] == "tool"]
    final = next(e for e in events if e["type"] == "final")
    assert len(tool_events) == 2
    assert final["steps"] == 2
