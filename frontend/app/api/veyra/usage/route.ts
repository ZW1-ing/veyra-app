import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 用量统计：转发到后端的聚合接口 */
export const runtime: ServerRuntime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const target = resolveBackend(request)
  const days = new URL(request.url).searchParams.get("days") ?? "14"

  try {
    const response = await fetch(`${target.baseUrl}/usage?days=${encodeURIComponent(days)}`, {
      headers: backendHeaders(target),
      cache: "no-store"
    })
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "请求后端失败"
    const hint = message.includes("ECONNREFUSED")
      ? `连不上 ${target.baseUrl}。请先在 backend/ 目录启动服务`
      : message
    return new Response(JSON.stringify({ message: hint }), {
      status: 502,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  }
}
