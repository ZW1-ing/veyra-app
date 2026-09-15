"use client"

import { MessageMarkdown } from "@/components/messages/message-markdown"
import {
  createSession,
  loadState,
  newId,
  saveState,
  titleFrom,
  toMarkdown,
  type LocalChatState,
  type LocalMessage,
  type LocalSession
} from "@/lib/local-chat/store"
import { IconDownload, IconPencil, IconPlus, IconTrash, IconX } from "@tabler/icons-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

/**
 * 本地模式对话页：不依赖 Supabase，也不需要登录。
 *
 * 浏览器 → /api/chat/veyra（本仓库的 Next 路由）→ Python 后端（backend/）。
 * 会话与消息存在浏览器 localStorage，后端另外维护自己的历史用于多轮上下文。
 */

const MODELS = [
  { id: "veyra-agent", label: "Veyra 智能体（带工具）" },
  { id: "veyra-swarm", label: "Veyra 蜂群（多智能体）" }
]

export default function LocalChatPage() {
  const [state, setState] = useState<LocalChatState>({ sessions: [], activeId: null })
  const [input, setInput] = useState("")
  const [model, setModel] = useState(MODELS[0].id)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [hydrated, setHydrated] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 首次进入：读本地会话；一个都没有就建一个
  useEffect(() => {
    const loaded = loadState()
    if (loaded.sessions.length === 0) {
      const session = createSession()
      setState({ sessions: [session], activeId: session.id })
    } else {
      const activeId =
        loaded.activeId && loaded.sessions.some((s) => s.id === loaded.activeId)
          ? loaded.activeId
          : loaded.sessions[0].id
      setState({ sessions: loaded.sessions, activeId })
    }
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (hydrated) saveState(state)
  }, [state, hydrated])

  const active = useMemo(
    () => state.sessions.find((s) => s.id === state.activeId) ?? null,
    [state]
  )

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [active?.messages.length, active?.id])

  const patchSession = useCallback(
    (id: string, patch: (session: LocalSession) => LocalSession) => {
      setState((current) => ({
        ...current,
        sessions: current.sessions.map((s) => (s.id === id ? patch(s) : s))
      }))
    },
    []
  )

  const addSession = useCallback(() => {
    const session = createSession()
    setState((current) => ({ sessions: [session, ...current.sessions], activeId: session.id }))
    setError("")
  }, [])

  const removeSession = useCallback((id: string) => {
    setState((current) => {
      const sessions = current.sessions.filter((s) => s.id !== id)
      if (sessions.length === 0) {
        const fresh = createSession()
        return { sessions: [fresh], activeId: fresh.id }
      }
      return {
        sessions,
        activeId: current.activeId === id ? sessions[0].id : current.activeId
      }
    })
  }, [])

  const exportSession = useCallback((session: LocalSession) => {
    const blob = new Blob([toMarkdown(session)], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${session.title.replace(/[\\/:*?"<>|]/g, "_") || "对话"}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }, [])

  const send = useCallback(async () => {
    const question = input.trim()
    if (!question || streaming || !active) return

    const userMessage: LocalMessage = { id: newId(), role: "user", content: question }
    const assistantMessage: LocalMessage = { id: newId(), role: "assistant", content: "" }
    const history = [...active.messages, userMessage]
    const sessionId = active.id

    patchSession(sessionId, (session) => ({
      ...session,
      // 第一条用户消息顺便给会话命名
      title: session.messages.length === 0 ? titleFrom(question) : session.title,
      updatedAt: Date.now(),
      messages: [...history, assistantMessage]
    }))
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
        const detail = (await response.json().catch(() => ({ message: "" }))) as { message?: string }
        throw new Error(detail.message || `请求失败（HTTP ${response.status}）`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        patchSession(sessionId, (session) => ({
          ...session,
          messages: session.messages.map((m) =>
            m.id === assistantMessage.id ? { ...m, content: m.content + chunk } : m
          )
        }))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败")
    } finally {
      setStreaming(false)
    }
  }, [active, input, model, patchSession, streaming])

  return (
    <div className="bg-background text-foreground flex h-dvh w-full">
      {/* 会话列表 */}
      <aside className="flex w-64 shrink-0 flex-col border-r">
        <div className="flex items-center justify-between border-b px-3 py-3">
          <span className="text-sm font-semibold">Veyra 本地模式</span>
          <button
            className="hover:bg-accent rounded-md p-1 disabled:opacity-50"
            onClick={addSession}
            title="新对话"
            disabled={streaming}
          >
            <IconPlus size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {state.sessions.map((session) => (
            <div
              key={session.id}
              className={`group mb-1 flex items-center gap-1 rounded-md px-2 py-1.5 text-sm ${
                session.id === state.activeId ? "bg-accent" : "hover:bg-accent/50"
              }`}
            >
              {renamingId === session.id ? (
                <input
                  autoFocus
                  className="border-input bg-background min-w-0 flex-1 rounded border px-1 py-0.5 text-sm"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      patchSession(session.id, (s) => ({ ...s, title: titleFrom(renameValue, 40) }))
                      setRenamingId(null)
                    } else if (e.key === "Escape") {
                      setRenamingId(null)
                    }
                  }}
                  onBlur={() => setRenamingId(null)}
                />
              ) : (
                <>
                  <button
                    className="min-w-0 flex-1 truncate text-left"
                    onClick={() => setState((current) => ({ ...current, activeId: session.id }))}
                    title={session.title}
                  >
                    {session.title}
                  </button>
                  <button
                    className="hover:bg-background rounded p-0.5 opacity-0 group-hover:opacity-100"
                    title="重命名"
                    onClick={() => {
                      setRenamingId(session.id)
                      setRenameValue(session.title)
                    }}
                  >
                    <IconPencil size={13} />
                  </button>
                  <button
                    className="hover:bg-background rounded p-0.5 opacity-0 group-hover:opacity-100"
                    title="删除"
                    onClick={() => removeSession(session.id)}
                  >
                    <IconTrash size={13} />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>

        <p className="text-muted-foreground border-t px-3 py-2 text-[11px] leading-relaxed">
          本地模式：无需登录，会话存在这台浏览器里。
        </p>
      </aside>

      {/* 对话区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b px-6 py-3">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold">{active?.title ?? "新对话"}</h1>
            <p className="text-muted-foreground text-xs">
              知识库检索 · 工具调用 · 多智能体，均由本机 Python 后端执行
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
              className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
              onClick={() => active && exportSession(active)}
              disabled={!active?.messages.length}
              title="导出为 Markdown"
            >
              <IconDownload size={14} />
              导出
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {!active?.messages.length && (
              <p className="text-muted-foreground text-sm">
                问点什么吧。回答会自动带上知识库来源（形如 [S1]）。
              </p>
            )}

            {active?.messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-1">
                <span className="text-muted-foreground text-xs">
                  {message.role === "user" ? "你" : "Veyra"}
                </span>
                <div className="text-sm leading-relaxed">
                  {message.role === "assistant" ? (
                    message.content ? (
                      <MessageMarkdown content={message.content} />
                    ) : (
                      <span className="text-muted-foreground">思考中…</span>
                    )
                  ) : (
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  )}
                </div>
              </div>
            ))}

            {error && (
              <div className="border-destructive/50 text-destructive flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
                <IconX size={16} className="mt-0.5 shrink-0" />
                <span>{error}</span>
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
    </div>
  )
}
