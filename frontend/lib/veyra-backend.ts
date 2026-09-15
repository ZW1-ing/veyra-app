/**
 * 解析「要连哪个 Python 后端」。
 *
 * 优先用请求头里的配置（来自前端设置页），没有就退回环境变量。
 * 只允许本机地址：这个代理是给本地模式用的，放开任意地址等于给了一个 SSRF 入口。
 */

export interface BackendTarget {
  baseUrl: string
  apiKey: string
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8000"

/** 只接受 127.0.0.1 / localhost / ::1 */
export function isLocalBaseUrl(baseUrl: string): boolean {
  try {
    const url = new URL(baseUrl)
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      ["127.0.0.1", "localhost", "::1", "[::1]"].includes(url.hostname)
    )
  } catch {
    return false
  }
}

export function normalizeBaseUrl(baseUrl: string): string {
  return (baseUrl || "").trim().replace(/\/+$/, "")
}

export function resolveBackend(request: Request): BackendTarget {
  const headerUrl = normalizeBaseUrl(request.headers.get("x-veyra-backend") ?? "")
  const envUrl = normalizeBaseUrl(process.env.VEYRA_API_URL ?? DEFAULT_BASE_URL)

  const baseUrl = headerUrl && isLocalBaseUrl(headerUrl) ? headerUrl : envUrl

  return {
    baseUrl,
    apiKey: request.headers.get("x-veyra-key") ?? process.env.VEYRA_API_KEY ?? ""
  }
}

export function backendHeaders(target: BackendTarget): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (target.apiKey) headers["X-API-Key"] = target.apiKey
  return headers
}

/**
 * 上传 multipart 时用这组头：**不能**手动设 Content-Type，
 * 否则会丢掉 fetch 自动生成的 boundary，后端解析失败。
 */
export function backendAuthHeaders(target: BackendTarget): Record<string, string> {
  return target.apiKey ? { "X-API-Key": target.apiKey } : {}
}
