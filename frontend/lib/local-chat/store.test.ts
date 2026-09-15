import { createSession, titleFrom, toMarkdown, type LocalSession } from "./store"

describe("titleFrom：用第一条提问给会话命名", () => {
  it("短句原样使用", () => {
    expect(titleFrom("什么是 RAG")).toBe("什么是 RAG")
  })

  it("过长时截断并加省略号", () => {
    const long = "这是一句很长的问题".repeat(10)
    const title = titleFrom(long, 20)
    expect(title).toHaveLength(21) // 20 个字符 + 省略号
    expect(title.endsWith("…")).toBe(true)
  })

  it("空白输入回落到默认名", () => {
    expect(titleFrom("   \n  ")).toBe("新对话")
  })

  it("把换行压成空格，避免侧栏显示断行", () => {
    expect(titleFrom("第一行\n第二行")).toBe("第一行 第二行")
  })
})

describe("createSession", () => {
  it("生成带 id 的空会话", () => {
    const session = createSession()
    expect(session.id).toBeTruthy()
    expect(session.title).toBe("新对话")
    expect(session.messages).toEqual([])
    expect(session.createdAt).toBeLessThanOrEqual(Date.now())
  })

  it("两次创建的 id 不同", () => {
    expect(createSession().id).not.toBe(createSession().id)
  })
})

describe("toMarkdown：导出对话", () => {
  const session: LocalSession = {
    id: "s1",
    title: "测试会话",
    createdAt: 0,
    updatedAt: 0,
    messages: [
      { id: "m1", role: "user", content: "工具调用上限是多少？" },
      { id: "m2", role: "assistant", content: "最多八步。[S1]" }
    ]
  }

  it("带标题、双方角色与正文", () => {
    const markdown = toMarkdown(session)
    expect(markdown).toContain("# 测试会话")
    expect(markdown).toContain("## 我")
    expect(markdown).toContain("## Veyra")
    expect(markdown).toContain("工具调用上限是多少？")
    expect(markdown).toContain("[S1]")
  })
})
