"use client"

import {
  loadAssistants,
  type Assistant,
  type PromptTemplate
} from "@/lib/local-chat/assistants"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut
} from "@/components/ui/command"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { backendRequestHeaders, loadSettings } from "@/lib/local-chat/settings"
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
import {
  IconChartBar,
  IconCopy,
  IconDatabase,
  IconDownload,
  IconDotsVertical,
  IconMessage,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconSettings,
  IconTrash,
  IconUsers,
  IconX
} from "@tabler/icons-react"
import dynamic from "next/dynamic"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

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

/**
 * Markdown 渲染器按需加载。
 *
 * react-markdown + 语法高亮加起来有几百 KB，直接静态引入会把它们塞进首屏包；
 * 对话页首屏其实只有输入框和空状态，等真有回答要渲染时再拉这个 chunk。
 */
const MessageMarkdown = dynamic(
  () => import("@/components/messages/message-markdown").then((mod) => mod.MessageMarkdown),
  {
    ssr: false,
    loading: () => <span className="text-muted-foreground">…</span>
  }
)

export default function LocalChatPage() {
  const router = useRouter()
  const [state, setState] = useState<LocalChatState>({ sessions: [], activeId: null })
  const [input, setInput] = useState("")
  const [model, setModel] = useState(MODELS[0].id)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [assistants, setAssistants] = useState<Assistant[]>([])
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [assistantId, setAssistantId] = useState("")
  const [pendingDelete, setPendingDelete] = useState<LocalSession | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 首次进入：读本地会话；一个都没有就建一个
  useEffect(() => {
    // 新会话的默认模式来自设置页
    const settings = loadSettings()
    if (settings.defaultModel) setModel(settings.defaultModel)

    // 助手与提示词模板来自 /local/assistants 页的配置
    const configured = loadAssistants()
    setAssistants(configured.assistants)
    setPrompts(configured.prompts)

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

  /**
   * 跑一轮对话。
   *
   * history 由调用方给出（已经包含本轮的提问）：
   * - 正常发送：追加一条新的用户消息
   * - 重新生成：传截断后的历史（结尾仍是原来那条用户消息，不重复追加）
   */
  const send = useCallback(
    async (question: string, history: LocalMessage[]) => {
    if (!question.trim() || streaming || !active) return

    const assistantMessage: LocalMessage = { id: newId(), role: "assistant", content: "" }
    const sessionId = active.id
    const assistant = assistants.find((a) => a.id === assistantId)

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
        // 带上前端设置里的后端地址与密钥（见 lib/veyra-backend.ts）
        headers: backendRequestHeaders(loadSettings()),
        body: JSON.stringify({
          chatSettings: { model, temperature: 0.5 },
          system_prompt: assistant?.systemPrompt || undefined,
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
    },
    [active, assistantId, assistants, model, patchSession, streaming]
  )

  /**
   * 重新生成：删掉这条回答，用它上面的用户提问重跑一轮。
   * 用户消息保持原样，这样会话历史里的上下文不会乱。
   */
  const regenerate = useCallback(
    async (assistantMessageId: string) => {
      if (streaming || !active) return
      const index = active.messages.findIndex((m) => m.id === assistantMessageId)
      if (index < 0) return

      const question = [...active.messages.slice(0, index)]
        .reverse()
        .find((m) => m.role === "user")?.content
      if (!question) return

      // 历史截到这条回答之前（结尾正是那条用户提问），不重复追加用户消息
      await send(question, active.messages.slice(0, index))
    },
    [active, send, streaming]
  )

  /** 输入框提交：把这条提问追加进历史后交给 send */
  const submit = useCallback(() => {
    if (!active) return
    const question = input.trim()
    if (!question || streaming) return
    const userMessage: LocalMessage = { id: newId(), role: "user", content: question }
    void send(question, [...active.messages, userMessage])
  }, [active, input, send, streaming])

  const copyMessage = useCallback(async (content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      toast.success("已复制到剪贴板")
    } catch {
      toast.error("复制失败，请手动选择文本")
    }
  }, [])

  /** 快捷键：⌘/Ctrl+K 打开会话面板，⌘/Ctrl+N 新建会话 */
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const modifier = event.metaKey || event.ctrlKey
      if (modifier && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
      if (modifier && event.key.toLowerCase() === "n") {
        event.preventDefault()
        addSession()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [addSession])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-w-0 flex-1">
      {/* 会话列表 */}
      <aside className="flex w-64 shrink-0 flex-col border-r">
        <div className="flex items-center justify-between border-b px-3 py-3">
          <span className="text-sm font-semibold">Veyra 本地模式</span>
          <div className="flex items-center gap-1">
            <button
              className="text-muted-foreground hover:bg-accent rounded px-1.5 py-0.5 text-[10px]"
              onClick={() => setPaletteOpen(true)}
              title="会话搜索与跳转（⌘/Ctrl + K）"
            >
              ⌘K
            </button>
            <button
              className="hover:bg-accent rounded-md p-1 disabled:opacity-50"
              onClick={addSession}
              title="新对话（⌘/Ctrl + N）"
              disabled={streaming}
            >
              <IconPlus size={16} />
            </button>
          </div>
        </div>

        <ScrollArea className="flex-1">
        <div className="p-2">
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
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        className="hover:bg-background rounded p-0.5 opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100"
                        title="更多操作"
                      >
                        <IconDotsVertical size={14} />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem
                        onClick={() => {
                          setRenamingId(session.id)
                          setRenameValue(session.title)
                        }}
                      >
                        <IconPencil size={14} className="mr-2" />
                        重命名
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => exportSession(session)}>
                        <IconDownload size={14} className="mr-2" />
                        导出 Markdown
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={() => setPendingDelete(session)}
                      >
                        <IconTrash size={14} className="mr-2" />
                        删除
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </>
              )}
            </div>
          ))}
        </div>
        </ScrollArea>

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
            {/* Radix Select 不接受空字符串作为 value，所以「不使用助手」用 none 这个哨兵值 */}
            <Select
              value={assistantId || "none"}
              onValueChange={(value) => {
                const id = value === "none" ? "" : value
                setAssistantId(id)
                // 选中助手时同时切换它预设的模型档位
                const picked = assistants.find((a) => a.id === id)
                if (picked?.model) setModel(picked.model)
              }}
              disabled={streaming}
            >
              <SelectTrigger className="w-[190px]" title="选择一个助手（角色设定会发给后端）">
                <SelectValue placeholder="不使用助手" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">不使用助手</SelectItem>
                {assistants.map((assistant) => (
                  <SelectItem key={assistant.id} value={assistant.id}>
                    {assistant.emoji} {assistant.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={model} onValueChange={setModel} disabled={streaming}>
              <SelectTrigger className="w-[210px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODELS.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
                  onClick={() => active && exportSession(active)}
                  disabled={!active?.messages.length}
                >
                  <IconDownload size={14} />
                  导出
                </button>
              </TooltipTrigger>
              <TooltipContent>把当前会话导出成 Markdown 文件</TooltipContent>
            </Tooltip>
          </div>
        </header>

        <ScrollArea className="flex-1">
        <main className="px-6 py-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {!active?.messages.length && (
              <div className="flex flex-col items-center gap-2 py-12 text-center">
                <IconMessage size={28} className="text-muted-foreground" />
                <p className="text-sm font-medium">开始一段新对话</p>
                <p className="text-muted-foreground max-w-md text-xs leading-relaxed">
                  回答会自动带上知识库来源（形如 [S1]）；顶部可以切换助手与模型档位，
                  按 ⌘/Ctrl + K 能快速在会话之间跳转。
                </p>
              </div>
            )}

            {active?.messages.map((message) => (
              <div key={message.id} className="group/message flex flex-col gap-1">
                <div className="flex h-5 items-center gap-2">
                  <span className="text-muted-foreground text-xs">
                    {message.role === "user" ? "你" : "Veyra"}
                  </span>
                  {/* 悬停才出现操作，避免平时干扰阅读 */}
                  {message.content && !streaming && (
                    <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover/message:opacity-100">
                      <button
                        className="hover:bg-accent rounded p-0.5"
                        title="复制这条消息"
                        onClick={() => void copyMessage(message.content)}
                      >
                        <IconCopy size={13} />
                      </button>
                      {message.role === "assistant" && (
                        <button
                          className="hover:bg-accent rounded p-0.5"
                          title="用同一个提问重新生成"
                          onClick={() => void regenerate(message.id)}
                        >
                          <IconRefresh size={13} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
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
        </ScrollArea>

        <footer className="border-t px-6 py-4">
          {prompts.length > 0 && (
            <div className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-1.5">
              {prompts.map((prompt) => (
                <button
                  key={prompt.id}
                  className="border-input text-muted-foreground hover:bg-accent hover:text-foreground rounded-full border px-2.5 py-1 text-xs"
                  title={prompt.content}
                  onClick={() =>
                    setInput((current) =>
                      current.trim() ? `${current.trim()}\n${prompt.content}` : prompt.content
                    )
                  }
                >
                  {prompt.name}
                </button>
              ))}
            </div>
          )}

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
                  submit()
                }
              }}
            />
            <button
              className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm disabled:opacity-50"
              onClick={submit}
              disabled={streaming || !input.trim()}
            >
              {streaming ? "生成中…" : "发送"}
            </button>
          </div>
        </footer>
      </div>
      </div>

      {/* 删除会话前确认：会话存在浏览器里，删掉就找不回来了 */}
      {/* 会话搜索与页面跳转：⌘/Ctrl + K */}
      <CommandDialog open={paletteOpen} onOpenChange={setPaletteOpen}>
        <CommandInput placeholder="搜索会话，或跳到某个页面…" />
        <CommandList>
          <CommandEmpty>没有匹配的内容</CommandEmpty>

          <CommandGroup heading="会话">
            {state.sessions.map((session) => (
              <CommandItem
                key={session.id}
                value={`${session.title} ${session.id}`}
                onSelect={() => {
                  setState((current) => ({ ...current, activeId: session.id }))
                  setPaletteOpen(false)
                }}
              >
                <IconMessage size={14} className="mr-2" />
                <span className="truncate">{session.title}</span>
              </CommandItem>
            ))}
          </CommandGroup>

          <CommandSeparator />

          <CommandGroup heading="操作">
            <CommandItem
              onSelect={() => {
                addSession()
                setPaletteOpen(false)
              }}
            >
              <IconPlus size={14} className="mr-2" />
              新建会话
              <CommandShortcut>⌘N</CommandShortcut>
            </CommandItem>
            {[
              { href: "/local/kb", label: "知识库", icon: IconDatabase },
              { href: "/local/assistants", label: "助手与提示词", icon: IconUsers },
              { href: "/local/usage", label: "用量统计", icon: IconChartBar },
              { href: "/local/settings", label: "设置", icon: IconSettings }
            ].map((item) => (
              <CommandItem
                key={item.href}
                onSelect={() => {
                  router.push(item.href)
                  setPaletteOpen(false)
                }}
              >
                <item.icon size={14} className="mr-2" />
                {item.label}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除这个会话？</AlertDialogTitle>
            <AlertDialogDescription>
              「{pendingDelete?.title}」里的对话记录会从这台浏览器移除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingDelete) removeSession(pendingDelete.id)
                setPendingDelete(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  )
}
