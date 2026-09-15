/**
 * 本地模式的前端设置：后端地址、API Key、默认编排方式。
 * 存在浏览器里，随请求头发给 Next 的代理路由（见 lib/veyra-backend.ts）。
 */

export interface LocalSettings {
  backendUrl: string
  apiKey: string
  /** 新建会话时的默认模型档位 */
  defaultModel: string
}

export const SETTINGS_KEY = "veyra-local-settings-v1"

export const DEFAULT_SETTINGS: LocalSettings = {
  backendUrl: "http://127.0.0.1:8000",
  apiKey: "",
  defaultModel: "veyra-agent"
}

export function loadSettings(): LocalSettings {
  if (typeof localStorage === "undefined") return DEFAULT_SETTINGS
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return DEFAULT_SETTINGS
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<LocalSettings>) }
  } catch {
    return DEFAULT_SETTINGS
  }
}

export function saveSettings(settings: LocalSettings): void {
  if (typeof localStorage === "undefined") return
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    // 存储不可用时忽略：当前会话仍然可用
  }
}

/** 所有访问后端的地方都带上这两个头，服务端据此决定连哪儿 */
export function backendRequestHeaders(settings: LocalSettings): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (settings.backendUrl) headers["X-Veyra-Backend"] = settings.backendUrl
  if (settings.apiKey) headers["X-Veyra-Key"] = settings.apiKey
  return headers
}
