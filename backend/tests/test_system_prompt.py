"""自定义系统提示词：前端选中的助手/提示词要真的进到模型请求里。"""

from app.agent.runner import stream_agent
from app.agent.tools import build_default_registry
from app.llm.mock import MockProvider


async def collect(events):
    return [event async for event in events]


async def test_custom_system_prompt_reaches_the_model():
    provider = MockProvider(["好的"])

    await collect(
        stream_agent(
            provider,
            build_default_registry(),
            [{"role": "user", "content": "你好"}],
            system_prompt="你是海盗，回答要带航海比喻",
        )
    )

    assert provider.calls, "模型应当被调用"
    system_message = provider.calls[0][0]
    assert system_message.role == "system"
    assert "你是海盗" in system_message.content
    # 工具协议等原有约束不能被挤掉
    assert "可用工具" in system_message.content


async def test_without_custom_prompt_system_message_has_no_persona_block():
    provider = MockProvider(["好的"])

    await collect(
        stream_agent(
            provider,
            build_default_registry(),
            [{"role": "user", "content": "你好"}],
        )
    )

    assert "角色设定" not in provider.calls[0][0].content


def test_chat_endpoint_accepts_system_prompt(client, app_instance):
    provider = MockProvider(["收到"])
    app_instance.state.provider = provider

    response = client.post(
        "/chat",
        json={"message": "你好", "system_prompt": "你是严谨的技术评审", "use_knowledge": False},
    )

    assert response.status_code == 200
    assert "你是严谨的技术评审" in provider.calls[0][0].content
