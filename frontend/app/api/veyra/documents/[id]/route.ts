import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 删除一篇文档及其分块 */
export const runtime: ServerRuntime = "nodejs"

export async function DELETE(
  request: Request,
  { params }: { params: { id: string } }
) {
  const target = resolveBackend(request)
  try {
    const response = await fetch(
      `${target.baseUrl}/kb/documents/${encodeURIComponent(params.id)}`,
      { method: "DELETE", headers: backendHeaders(target) }
    )
    if (response.status === 204) {
      return new Response(null, { status: 204 })
    }
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "请求后端失败"
    const hint = message.includes("ECONNREFUSED")
      ? `连不上 Veyra 后端（${target.baseUrl}），请先启动 backend/ 里的服务`
      : message
    return new Response(JSON.stringify({ message: hint }), {
      status: 502,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  }
}
