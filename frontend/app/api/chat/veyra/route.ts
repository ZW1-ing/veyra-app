import { createHash } from "node:crypto"
import { ServerRuntime } from "next"
import { backendHeaders, resolveBackend } from "@/lib/veyra-backend"

/**
 * 把前端的聊天请求转给自建的 Python 后端。
 *
 * 这里刻意用 Node runtime 而不是 edge：后端跑在本机（127.0.0.1），
 * edge runtime 连不到宿主机；而且我们要用 node:crypto 生成稳定的会话 id。
 */
export const runtime: ServerRuntime = "nodejs"
export const dynamic = "force-dynamic"

interface IncomingMessage {
  id?: string
  role?: string
  content?: string
}

/**
 * 前端会话 → 后端会话 id。
 *
 * 后端的会话 id 列是 32 位，而前端的消息 id 是 uuid（36 位），
 * 直接传会被 MySQL 拒绝；这里取首条消息 id 的 sha256 前 32 位：
 * 同一个会话的首条消息不变，于是每轮都映射到同一个后端会话，历史就能接上。
 */
function toBackendSessionId(messages: IncomingMessage[]): string {
  const seed = messages[0]?.id ?? messages[0]?.content ?? "veyra-anonymous"
  return createHash("sha256").update(String(seed)).digest("hex").slice(0, 32)
}

function lastUserMessage(messages: IncomingMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role === "user" && messages[i]?.content) {
      return String(messages[i].content)
    }
  }
  return ""
}

/** 把后端的 SSE 事件流，翻译成前端能直接显示的纯文本流 */
function toTextStream(
  upstream: ReadableStream<Uint8Array>
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder()
  const encoder = new TextEncoder()
  const reader = upstream.getReader()

  return new ReadableStream<Uint8Array>({
    // 用 start 里的一次性循环泵数据，而不是 pull()：
    // pull 版本在「上游结束」与「客户端等待结束」之间容易漏掉 close，
    // 表现就是内容已经显示完了、连接还挂着不结束（浏览器一直转圈）。
    async start(controller) {
      let buffer = ""
      let sources: string[] = []
      let closed = false
      const close = (): void => {
        if (closed) return
        closed = true
        controller.close()
      }

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const blocks = buffer.split("\n\n")
          buffer = blocks.pop() ?? ""

          for (const block of blocks) {
            for (const line of block.split("\n")) {
              if (!line.startsWith("data:")) continue
              const payload = line.slice(5).trim()
              if (!payload || payload === "[DONE]") continue

              let event: Record<string, unknown>
              try {
                event = JSON.parse(payload)
              } catch {
                continue
              }

              if (event.type === "token" && event.text) {
                controller.enqueue(encoder.encode(String(event.text)))
              } else if (event.type === "meta" && Array.isArray(event.sources)) {
                sources = event.sources.map(
                  (item) =>
                    `[${(item as Record<string, unknown>).id}] ${(item as Record<string, unknown>).document_name}`
                )
              } else if (event.type === "error") {
                controller.enqueue(encoder.encode(`\n\n[服务端错误] ${String(event.message ?? "")}`))
              }
            }
          }
        }

        if (sources.length) {
          // 用 Markdown 列表收尾：前端直接用 Markdown 组件渲染，来源就是一份可读的清单
          const list = sources.map((item) => `- ${item}`).join("\n")
          controller.enqueue(encoder.encode(`\n\n**来源**\n\n${list}\n`))
        }
        close()
      } catch (error) {
        if (!closed) {
          closed = true
          controller.error(error)
        }
      } finally {
        reader.releaseLock()
      }
    },
    cancel() {
      void reader.cancel()
    }
  })
}

export async function POST(request: Request) {
  let messages: IncomingMessage[] = []
  let model = ""

  try {
    const json = await request.json()
    messages = (json.messages ?? []) as IncomingMessage[]
    model = String(json.chatSettings?.model ?? "")
    const systemPrompt = typeof json.system_prompt === "string" ? json.system_prompt : undefined

    const question = lastUserMessage(messages)
    if (!question) {
      return new Response(JSON.stringify({ message: "没有找到用户消息" }), { status: 400 })
    }

    // 后端地址与密钥来自请求头（前端设置页）或环境变量，见 lib/veyra-backend.ts
    const target = resolveBackend(request)

    const upstream = await fetch(`${target.baseUrl}/chat/stream`, {
      method: "POST",
      headers: backendHeaders(target),
      body: JSON.stringify({
        message: question,
        // 模型名决定编排方式：蜂群档位走多智能体，其余走单智能体
        mode: model.includes("swarm") ? "swarm" : "single",
        use_knowledge: true,
        session_id: toBackendSessionId(messages),
        // 前端选中的助手/提示词：后端会拼进系统提示词
        system_prompt: systemPrompt
      }),
      signal: request.signal
    })

    if (!upstream.ok || !upstream.body) {
      const detail = await upstream.text().catch(() => "")
      return new Response(
        JSON.stringify({
          message: `Veyra 后端返回 ${upstream.status}${detail ? `：${detail.slice(0, 200)}` : ""}`
        }),
        { status: 502 }
      )
    }

    return new Response(toTextStream(upstream.body), {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
      }
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : "请求 Veyra 后端失败"
    const target = resolveBackend(request)

    // 后端没起的时候给出可执行的提示，而不是一句「服务器错误」
    const hint = message.includes("ECONNREFUSED")
      ? `连不上 Veyra 后端（${target.baseUrl}）。请先在 backend/ 目录启动服务：uvicorn app.main:app --port 8000`
      : message

    return new Response(JSON.stringify({ message: hint }), { status: 502 })
  }
}
