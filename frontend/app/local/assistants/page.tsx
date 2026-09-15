"use client"

import {
  ASSISTANTS_KEY,
  createAssistant,
  createPrompt,
  loadAssistants,
  saveAssistants,
  type AssistantsState
} from "@/lib/local-chat/assistants"
import { IconPlus, IconTrash } from "@tabler/icons-react"
import { useCallback, useEffect, useState } from "react"

const MODELS = [
  { id: "veyra-agent", label: "Veyra 智能体（带工具）" },
  { id: "veyra-swarm", label: "Veyra 蜂群（多智能体）" }
]

/**
 * 助手与提示词管理。
 *
 * 助手 = 角色设定 + 默认模型；提示词 = 一段可复用的指令文本。
 * 都存在浏览器本地，会话里选中助手后会把系统提示词发给后端。
 */
export default function AssistantsPage() {
  const [state, setState] = useState<AssistantsState>({ assistants: [], prompts: [] })
  const [hydrated, setHydrated] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setState(loadAssistants())
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (!hydrated) return
    saveAssistants(state)
    setSaved(true)
    const timer = setTimeout(() => setSaved(false), 1200)
    return () => clearTimeout(timer)
  }, [state, hydrated])

  const addAssistant = useCallback(() => {
    setState((current) => ({ ...current, assistants: [...current.assistants, createAssistant()] }))
  }, [])

  const addPrompt = useCallback(() => {
    setState((current) => ({ ...current, prompts: [...current.prompts, createPrompt()] }))
  }, [])

  const removeAssistant = useCallback((id: string) => {
    setState((current) => ({
      ...current,
      assistants: current.assistants.filter((a) => a.id !== id)
    }))
  }, [])

  const removePrompt = useCallback((id: string) => {
    setState((current) => ({ ...current, prompts: current.prompts.filter((p) => p.id !== id) }))
  }, [])

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <div>
          <h1 className="text-base font-semibold">助手与提示词</h1>
          <p className="text-muted-foreground text-xs">
            助手 = 角色设定 + 默认模型；在会话顶部选中后生效。全部保存在这台浏览器里。
          </p>
        </div>
        <span className="text-muted-foreground text-xs">{saved ? "已自动保存" : ""}</span>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-3xl flex-col gap-8">
          {/* 助手 */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">助手（{state.assistants.length}）</h2>
              <button
                className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm"
                onClick={addAssistant}
              >
                <IconPlus size={14} />
                新增助手
              </button>
            </div>

            {state.assistants.map((assistant, index) => (
              <div key={assistant.id} className="flex flex-col gap-2 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <input
                    className="border-input bg-background w-14 rounded-md border px-2 py-1.5 text-center text-sm"
                    value={assistant.emoji}
                    maxLength={2}
                    onChange={(e) =>
                      setState((current) => ({
                        ...current,
                        assistants: current.assistants.map((a) =>
                          a.id === assistant.id ? { ...a, emoji: e.target.value } : a
                        )
                      }))
                    }
                  />
                  <input
                    className="border-input bg-background flex-1 rounded-md border px-3 py-1.5 text-sm"
                    placeholder="助手名称"
                    value={assistant.name}
                    onChange={(e) =>
                      setState((current) => ({
                        ...current,
                        assistants: current.assistants.map((a) =>
                          a.id === assistant.id ? { ...a, name: e.target.value } : a
                        )
                      }))
                    }
                  />
                  <select
                    className="border-input bg-background rounded-md border px-2 py-1.5 text-sm"
                    value={assistant.model}
                    onChange={(e) =>
                      setState((current) => ({
                        ...current,
                        assistants: current.assistants.map((a) =>
                          a.id === assistant.id ? { ...a, model: e.target.value } : a
                        )
                      }))
                    }
                  >
                    {MODELS.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                  <button
                    className="hover:bg-destructive/10 text-destructive rounded p-1.5"
                    title="删除助手"
                    onClick={() => removeAssistant(assistant.id)}
                  >
                    <IconTrash size={15} />
                  </button>
                </div>

                <textarea
                  className="border-input bg-background min-h-[96px] rounded-md border px-3 py-2 text-sm"
                  placeholder="角色设定：你是谁、回答要遵循什么规则"
                  value={assistant.systemPrompt}
                  onChange={(e) =>
                    setState((current) => ({
                      ...current,
                      assistants: current.assistants.map((a) =>
                        a.id === assistant.id ? { ...a, systemPrompt: e.target.value } : a
                      )
                    }))
                  }
                />
                <span className="text-muted-foreground text-[11px]">
                  第 {index + 1} 个助手 · 会话里选中后，这段文字会作为系统提示词发给后端
                </span>
              </div>
            ))}
          </section>

          {/* 提示词 */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">提示词模板（{state.prompts.length}）</h2>
              <button
                className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm"
                onClick={addPrompt}
              >
                <IconPlus size={14} />
                新增提示词
              </button>
            </div>

            {state.prompts.map((prompt) => (
              <div key={prompt.id} className="flex flex-col gap-2 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <input
                    className="border-input bg-background flex-1 rounded-md border px-3 py-1.5 text-sm"
                    placeholder="提示词名称"
                    value={prompt.name}
                    onChange={(e) =>
                      setState((current) => ({
                        ...current,
                        prompts: current.prompts.map((p) =>
                          p.id === prompt.id ? { ...p, name: e.target.value } : p
                        )
                      }))
                    }
                  />
                  <button
                    className="hover:bg-destructive/10 text-destructive rounded p-1.5"
                    title="删除提示词"
                    onClick={() => removePrompt(prompt.id)}
                  >
                    <IconTrash size={15} />
                  </button>
                </div>
                <textarea
                  className="border-input bg-background min-h-[64px] rounded-md border px-3 py-2 text-sm"
                  placeholder="提示词内容"
                  value={prompt.content}
                  onChange={(e) =>
                    setState((current) => ({
                      ...current,
                      prompts: current.prompts.map((p) =>
                        p.id === prompt.id ? { ...p, content: e.target.value } : p
                      )
                    }))
                  }
                />
              </div>
            ))}

            <p className="text-muted-foreground text-xs">
              提示词的存储 key 是 <code>{ASSISTANTS_KEY}</code>，清空浏览器数据会一起清掉。
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
