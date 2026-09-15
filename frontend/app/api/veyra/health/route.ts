import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 设置页的「测试连接」：把后端健康检查转发出去 */
export const runtime: ServerRuntime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const target = resolveBackend(request)
  try {
    const response = await fetch(`${target.baseUrl}/health`, {
      headers: backendHeaders(target),
      cache: "no-store"
    })
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "连接失败"
    const hint = message.includes("ECONNREFUSED")
      ? `连不上 ${target.baseUrl}。请先在 backend/ 目录启动服务：uvicorn app.main:app --port 8000`
      : message
    return new Response(JSON.stringify({ message: hint }), {
      status: 502,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  }
}
