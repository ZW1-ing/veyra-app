/**
 * 助手（角色）与提示词模板的本地存储。
 *
 * 助手 = 一段系统提示词 + 默认模型档位；在会话里选中后，会随请求发给后端
 * （后端把它拼进系统提示词，见 backend/app/agent/prompts.py）。
 */

export interface PromptTemplate {
  id: string
  name: string
  content: string
  createdAt: number
}

export interface Assistant {
  id: string
  name: string
  emoji: string
  systemPrompt: string
  model: string
  createdAt: number
}

export interface AssistantsState {
  assistants: Assistant[]
  prompts: PromptTemplate[]
}

export const ASSISTANTS_KEY = "veyra-local-assistants-v1"

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `a-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function createAssistant(partial: Partial<Assistant> = {}): Assistant {
  return {
    id: newId(),
    name: partial.name ?? "新助手",
    emoji: partial.emoji ?? "🤖",
    systemPrompt: partial.systemPrompt ?? "",
    model: partial.model ?? "veyra-agent",
    createdAt: Date.now()
  }
}

export function createPrompt(partial: Partial<PromptTemplate> = {}): PromptTemplate {
  return {
    id: newId(),
    name: partial.name ?? "新提示词",
    content: partial.content ?? "",
    createdAt: Date.now()
  }
}

/** 首次使用时给几个能直接用的例子，而不是空列表 */
function seed(): AssistantsState {
  return {
    assistants: [
      createAssistant({
        name: "严谨技术评审",
        emoji: "🧐",
        model: "veyra-agent",
        systemPrompt:
          "你是严谨的技术评审。回答必须区分「有依据的结论」和「你的推测」，" +
          "能引用资料时标注来源编号；发现需求或方案里有漏洞时直接指出，不要迎合。"
      }),
      createAssistant({
        name: "面试官模拟",
        emoji: "🎤",
        model: "veyra-agent",
        systemPrompt:
          "你是 AI 应用开发岗位的面试官。每次先针对候选人回答里的薄弱点追问一个问题，" +
          "再给出简短评价与改进建议；追问要具体，不要泛泛而谈。"
      }),
      createAssistant({
        name: "调研小组",
        emoji: "🧭",
        model: "veyra-swarm",
        systemPrompt:
          "把任务拆给不同角色：一人负责检索资料、一人负责核对与挑错、一人负责成文。" +
          "结论必须能追溯到资料来源。"
      })
    ],
    prompts: [
      createPrompt({
        name: "要点总结",
        content: "把上面的内容总结成不超过五条要点，每条一行，去掉修饰语。"
      }),
      createPrompt({
        name: "代码解释",
        content: "逐段解释这段代码：它做什么、关键取舍是什么、有什么潜在问题。"
      }),
      createPrompt({
        name: "面试追问",
        content: "针对我的回答，追问三个能暴露理解深度的问题，不要给答案。"
      })
    ]
  }
}

export function loadAssistants(): AssistantsState {
  if (typeof localStorage === "undefined") return seed()
  try {
    const raw = localStorage.getItem(ASSISTANTS_KEY)
    if (!raw) return seed()
    const parsed = JSON.parse(raw) as Partial<AssistantsState>
    return {
      assistants: parsed.assistants ?? [],
      prompts: parsed.prompts ?? []
    }
  } catch {
    return seed()
  }
}

export function saveAssistants(state: AssistantsState): void {
  if (typeof localStorage === "undefined") return
  try {
    localStorage.setItem(ASSISTANTS_KEY, JSON.stringify(state))
  } catch {
    // 配额满等情况忽略：不影响当前会话
  }
}
