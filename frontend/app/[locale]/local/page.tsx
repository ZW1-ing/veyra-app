"use client"

import { MessageMarkdown } from "@/components/messages/message-markdown"
import { useCallback, useEffect, useRef, useState } from "react"

/**
 * 本地模式对话页：不依赖 Supabase，也不需要登录。
 *
 * 浏览器 → /api/chat/veyra（本仓库的 Next 路由）→ Python 后端（backend/）。
 * 会话内容存在浏览器 localStorage 里，后端另外维护自己的会话历史（用于多轮上下文）。
 */

type Role = "user" | "assistant"

interface LocalMessage {
  id: string
  role: Role
  content: string
}

const STORAGE_KEY = "veyra-local-chat-v1"

const MODELS = [
  { id: "veyra-agent", label: "Veyra 智能体（带工具）" },
  { id: "veyra-swarm", label: "Veyra 蜂群（多智能体）" }
]

function newId(): string {
  // 后端会话 id 由首条消息 id 派生，所以要稳定且唯一
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export default function LocalChatPage() {
  const [messages, setMessages] = useState<LocalMessage[]>([])
  const [input, setInput] = useState("")
  const [model, setModel] = useState(MODELS[0].id)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)

  // 开场先塞一条 system 之外的空对话：用首条用户消息的 id 作为后端会话种子，
  // 所以这里只做本地恢复，不再额外生成 id。
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) setMessages(JSON.parse(saved) as LocalMessage[])
    } catch {
      // 本地缓存坏了不影响使用，忽略即可
    }
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
    } catch {
      // 存储满了之类的情况忽略
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const send = useCallback(async () => {
    const question = input.trim()
    if (!question || streaming) return

    const userMessage: LocalMessage = { id: newId(), role: "user", content: question }
    const assistantMessage: LocalMessage = { id: newId(), role: "assistant", content: "" }
    const history = [...messages, userMessage]

    setMessages([...history, assistantMessage])
    setInput("")
    setStreaming(true)
    setError("")

    try {
      const response = await fetch("/api/chat/veyra", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chatSettings: { model, temperature: 0.5 },
          // 首条消息的 id 决定后端会话，从而决定多轮上下文
          messages: history.map((m) => ({ id: m.id, role: m.role, content: m.content }))
        })
      })

      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => ({ message: "" }))
        throw new Error(detail.message || `请求失败（HTTP ${response.status}）`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        setMessages((current) =>
          current.map((m) =>
            m.id === assistantMessage.id ? { ...m, content: m.content + chunk } : m
          )
        )
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败")
    } finally {
      setStreaming(false)
    }
  }, [input, messages, model, streaming])

  return (
    <div className="flex h-dvh w-full flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 border-b px-6 py-3">
        <div>
          <h1 className="text-lg font-semibold">Veyra 本地模式</h1>
          <p className="text-muted-foreground text-xs">
            不依赖 Supabase，直接连本机的 Python 后端（知识库检索 · 工具调用 · 多智能体）
          </p>
        </div>

        <div className="flex items-center gap-2">
          <select
            className="border-input bg-background rounded-md border px-3 py-1.5 text-sm"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={streaming}
          >
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
          <button
            className="border-input hover:bg-accent rounded-md border px-3 py-1.5 text-sm"
            onClick={() => {
              setMessages([])
              setError("")
            }}
            disabled={streaming}
          >
            新对话
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          {messages.length === 0 && (
            <p className="text-muted-foreground text-sm">
              问点什么吧。回答会自动带上知识库来源（形如 [S1]）。
            </p>
          )}

          {messages.map((m) => (
            <div key={m.id} className="flex flex-col gap-1">
              <span className="text-muted-foreground text-xs">
                {m.role === "user" ? "你" : "Veyra"}
              </span>
              <div className="text-sm leading-relaxed">
                {m.role === "assistant" ? (
                  m.content ? (
                    <MessageMarkdown content={m.content} />
                  ) : (
                    <span className="text-muted-foreground">思考中…</span>
                  )
                ) : (
                  <p className="whitespace-pre-wrap">{m.content}</p>
                )}
              </div>
            </div>
          ))}

          {error && (
            <div className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      <footer className="border-t px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-3">
          <textarea
            className="border-input bg-background min-h-[44px] flex-1 resize-none rounded-md border px-3 py-2 text-sm"
            rows={1}
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
          />
          <button
            className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm disabled:opacity-50"
            onClick={() => void send()}
            disabled={streaming || !input.trim()}
          >
            {streaming ? "生成中…" : "发送"}
          </button>
        </div>
      </footer>
    </div>
  )
}
