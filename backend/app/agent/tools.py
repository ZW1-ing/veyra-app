"""工具注册表：模型能调用的能力都在这里登记。

模型看到的只有「名字 + 说明 + 参数」，看不到实现；
执行时任何异常都会被兜住并转成文本返回给模型，避免一次工具报错打断整轮对话。
"""

import ast
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)
    func: Callable[..., str] = lambda **_: ""

    def spec_text(self) -> str:
        params = "、".join(f"{k}（{v}）" for k, v in self.parameters.items()) or "无"
        return f"- {self.name}：{self.description}；参数：{params}"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs_text(self) -> str:
        if not self._tools:
            return "（当前没有可用工具）"
        return "\n".join(tool.spec_text() for tool in self._tools.values())

    def run(self, name: str, args: dict) -> tuple[bool, str]:
        """执行工具。返回 (是否成功, 文本结果)。"""
        tool = self._tools.get(name)
        if tool is None:
            return False, f"工具 {name} 不存在，可用工具：{', '.join(self.names())}"
        try:
            return True, str(tool.func(**(args or {})))
        except TypeError as exc:
            return False, f"参数不匹配：{exc}"
        except Exception as exc:  # noqa: BLE001 工具内部错误不能掀翻整轮对话
            return False, f"工具执行失败：{type(exc).__name__}: {exc}"


# ---------- 内置工具 ----------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    """只允许数字与四则运算，避免用 eval 带来的任意代码执行风险。"""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("只支持数字与 + - * / // % ** 运算")


def tool_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tool_calc(expression: str = "") -> str:
    tree = ast.parse(str(expression), mode="eval")
    value = _eval_node(tree)
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_default_registry(kb_search: Callable[[str], str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="now",
            description="查询当前本地时间",
            parameters={},
            func=lambda **_: tool_now(),
        )
    )
    registry.register(
        Tool(
            name="calc",
            description="计算数学表达式",
            parameters={"expression": "要计算的表达式，例如 (23+47)*2"},
            func=tool_calc,
        )
    )
    if kb_search is not None:
        registry.register(
            Tool(
                name="kb_search",
                description="在本地知识库中检索资料，返回带 [S1] 编号的片段",
                parameters={"query": "检索关键词或问题"},
                func=kb_search,
            )
        )
    return registry
