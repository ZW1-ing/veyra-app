/**
 * 本地模式的会话存储。
 *
 * 会话与消息都存在浏览器 localStorage 里（不依赖 Supabase）；
 * 后端只负责生成回答，它另外维护自己的会话历史用于多轮上下文，
 * 两边的会话通过「首条消息 id」关联（见 app/api/chat/veyra/route.ts）。
 */

export type Role = "user" | "assistant"

export interface LocalMessage {
  id: string
  role: Role
  content: string
}

export interface LocalSession {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: LocalMessage[]
}

export interface LocalChatState {
  sessions: LocalSession[]
  activeId: string | null
}

export const STORAGE_KEY = "veyra-local-sessions-v1"

export function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `m-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function createSession(): LocalSession {
  const now = Date.now()
  return { id: newId(), title: "新对话", createdAt: now, updatedAt: now, messages: [] }
}

/** 用第一条用户消息给会话起个名，太长就截断 */
export function titleFrom(text: string, max = 20): string {
  const clean = text.replace(/\s+/g, " ").trim()
  if (!clean) return "新对话"
  return clean.length > max ? `${clean.slice(0, max)}…` : clean
}

export function loadState(): LocalChatState {
  if (typeof localStorage === "undefined") return { sessions: [], activeId: null }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { sessions: [], activeId: null }
    const parsed = JSON.parse(raw) as LocalChatState
    if (!Array.isArray(parsed.sessions)) return { sessions: [], activeId: null }
    return { sessions: parsed.sessions, activeId: parsed.activeId ?? null }
  } catch {
    // 缓存损坏时当作空状态，不让它把页面卡死
    return { sessions: [], activeId: null }
  }
}

export function saveState(state: LocalChatState): void {
  if (typeof localStorage === "undefined") return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储配额满了之类的情况忽略：不影响当前会话继续用
  }
}

/** 导出成 Markdown，方便贴到别处或存进知识库 */
export function toMarkdown(session: LocalSession): string {
  const lines = [`# ${session.title}`, "", `> 导出于 ${new Date().toLocaleString()}`, ""]
  for (const message of session.messages) {
    lines.push(message.role === "user" ? "## 我" : "## Veyra", "", message.content, "")
  }
  return lines.join("\n")
}
