import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 知识库管理：列出文档 / 新增文档（转发到 Python 后端） */
export const runtime: ServerRuntime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const target = resolveBackend(request)
  try {
    const response = await fetch(`${target.baseUrl}/kb/documents`, {
      headers: backendHeaders(target),
      cache: "no-store"
    })
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    return backendUnreachable(error, target.baseUrl)
  }
}

export async function POST(request: Request) {
  const target = resolveBackend(request)
  try {
    const payload = await request.json()
    const response = await fetch(`${target.baseUrl}/kb/documents`, {
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
    return backendUnreachable(error, target.baseUrl)
  }
}

function backendUnreachable(error: unknown, baseUrl: string): Response {
  const message = error instanceof Error ? error.message : "请求后端失败"
  const hint = message.includes("ECONNREFUSED")
    ? `连不上 Veyra 后端（${baseUrl}）。请先在 backend/ 目录启动服务：uvicorn app.main:app --port 8000`
    : message
  return new Response(JSON.stringify({ message: hint }), {
    status: 502,
    headers: { "Content-Type": "application/json; charset=utf-8" }
  })
}
