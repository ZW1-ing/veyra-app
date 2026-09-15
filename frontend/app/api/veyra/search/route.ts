import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 检索调试：直接看某个问题会命中哪些片段，方便调分块与阈值 */
export const runtime: ServerRuntime = "nodejs"

export async function POST(request: Request) {
  const target = resolveBackend(request)
  try {
    const payload = await request.json()
    const response = await fetch(`${target.baseUrl}/kb/search`, {
      method: "POST",
      headers: backendHeaders(target),
      body: JSON.stringify(payload)
    })
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "请求后端失败"
    return new Response(JSON.stringify({ message }), {
      status: 502,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  }
}
