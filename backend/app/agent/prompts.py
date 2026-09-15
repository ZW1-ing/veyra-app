"""提示词模板：工具调用协议 + 引用规范都写在这里，方便单独迭代。"""

TOOL_PROTOCOL = """需要调用工具时，只输出一行 JSON，不要输出别的文字：
{"tool": "工具名", "args": {"参数名": "参数值"}}

拿到工具结果后，再决定是继续调用工具还是给出最终回答。
不需要调用工具时，直接用中文回答用户。"""


def build_system_prompt(tool_specs: str, max_steps: int) -> str:
    return f"""你是 Veyra 的 AI 助手，回答要准确、简洁，不确定时明确说明。

可用工具：
{tool_specs}

{TOOL_PROTOCOL}

约束：
1. 最多调用 {max_steps} 步工具，超过就基于已有信息作答。
2. 如果上下文里提供了资料片段，引用时标注编号，例如 [S1]；没有依据不要编造。
3. 最终回答直接给结论，不要复述工具调用过程。"""


def extract_action(text: str) -> dict | None:
    """从模型输出里抠出工具调用 JSON。

    模型有时会把 JSON 包在 ```json 里或前后加解释，所以按「最后一个
    含 tool 字段的 JSON 对象」来解析，容错优先。
    """
    import json
    import re

    if not text or '"tool"' not in text:
        return None

    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates.extend(fenced)
    candidates.extend(re.findall(r"\{[^{}]*\"tool\"[^{}]*\}", text, flags=re.S))
    candidates.append(text.strip())

    for candidate in reversed(candidates):
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("tool"), str):
            args = payload.get("args")
            return {"tool": payload["tool"], "args": args if isinstance(args, dict) else {}}
    return None
