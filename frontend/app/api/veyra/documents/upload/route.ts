import { ServerRuntime } from "next"
import { backendAuthHeaders, resolveBackend } from "@/lib/veyra-backend"

/** 文件上传：转发 multipart 到后端解析入库（txt / markdown / PDF / DOCX） */
export const runtime: ServerRuntime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST(request: Request) {
  const target = resolveBackend(request)

  try {
    const incoming = await request.formData()
    const file = incoming.get("file")
    if (!(file instanceof File)) {
      return json({ message: "没有收到文件" }, 400)
    }

    const outgoing = new FormData()
    outgoing.append("file", file, file.name)
    for (const key of ["chunk_size", "chunk_overlap"]) {
      const value = incoming.get(key)
      if (typeof value === "string" && value) outgoing.append(key, value)
    }

    const response = await fetch(`${target.baseUrl}/kb/documents/upload`, {
      method: "POST",
      // 不设 Content-Type：交给 fetch 生成 multipart boundary
      headers: backendAuthHeaders(target),
      body: outgoing
    })
    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: { "Content-Type": "application/json; charset=utf-8" }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "上传失败"
    const hint = message.includes("ECONNREFUSED")
      ? `连不上 ${target.baseUrl}。请先在 backend/ 目录启动服务`
      : message
    return json({ message: hint }, 502)
  }
}

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" }
  })
}
