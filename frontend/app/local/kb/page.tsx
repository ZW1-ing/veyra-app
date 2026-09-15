"use client"

import { backendRequestHeaders, loadSettings } from "@/lib/local-chat/settings"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { IconRefresh, IconTrash, IconUpload } from "@tabler/icons-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { useRef } from "react"

/**
 * 知识库管理：把文档灌进后端（backend/ 的 /kb/documents），并管理已有文档。
 * 面试里最能演示的一步：上传一篇文档 → 回会话里提问 → 回答带 [S1] 引用。
 */

interface DocumentItem {
  id: string
  name: string
  source_type: string
  char_count: number
  chunk_size: number
  embedding_model: string
  embedding_dim: number
  created_at: string
}

interface SearchHit {
  id: string
  document_name: string
  chunk_index: number
  preview: string
  score: number
}

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [name, setName] = useState("")
  const [text, setText] = useState("")
  const [chunkSize, setChunkSize] = useState("")
  const [loading, setLoading] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [query, setQuery] = useState("")
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch("/api/veyra/documents", {
        headers: backendRequestHeaders(loadSettings()),
        cache: "no-store"
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || `加载失败（HTTP ${response.status}）`)
      setDocuments(body as DocumentItem[])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const ingest = useCallback(async () => {
    if (!name.trim() || !text.trim()) return
    setLoading(true)
    try {
      const payload: Record<string, unknown> = { name: name.trim(), text }
      const size = Number(chunkSize)
      if (chunkSize && Number.isFinite(size) && size >= 50) {
        payload.chunk_size = Math.round(size)
        payload.chunk_overlap = 0
      }

      const response = await fetch("/api/veyra/documents", {
        method: "POST",
        headers: backendRequestHeaders(loadSettings()),
        body: JSON.stringify(payload)
      })
      const body = await response.json()
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : body.message || `入库失败（HTTP ${response.status}）`
        )
      }
      toast.success(
        body.deduplicated
          ? "内容与配置都没变，后端复用了已有记录（没有重复入库）"
          : `已入库：${body.name}（${body.char_count} 字，块大小 ${body.chunk_size}，模型 ${body.embedding_model}）`
      )
      setName("")
      setText("")
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "入库失败")
    } finally {
      setLoading(false)
    }
  }, [chunkSize, name, refresh, text])

  const remove = useCallback(
    async (document: DocumentItem) => {
      try {
        const response = await fetch(`/api/veyra/documents/${document.id}`, {
          method: "DELETE",
          headers: backendRequestHeaders(loadSettings())
        })
        if (response.status !== 204) {
          const body = await response.json().catch(() => ({ message: "" }))
          throw new Error(body.message || `删除失败（HTTP ${response.status}）`)
        }
        toast.success(`已删除：${document.name}`)
        await refresh()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "删除失败")
      }
    },
    [refresh]
  )

  const search = useCallback(async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const response = await fetch("/api/veyra/search", {
        method: "POST",
        headers: backendRequestHeaders(loadSettings()),
        body: JSON.stringify({ query: query.trim(), top_k: 5 })
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || `检索失败（HTTP ${response.status}）`)
      setHits(body as SearchHit[])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "检索失败")
    } finally {
      setSearching(false)
    }
  }, [query])

  const onPickFile = useCallback(async (file: File) => {
    const content = await file.text()
    setName(file.name)
    setText(content)
    toast.success(`已读取 ${file.name}（${content.length} 字），确认后点「入库」`)
  }, [])

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <div>
          <h1 className="text-base font-semibold">知识库</h1>
          <p className="text-muted-foreground text-xs">
            文档入库后会参与检索，回答里会带上 [S1] 这样的来源编号
          </p>
        </div>
        <button
          className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <IconRefresh size={14} />
          刷新
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-4xl flex-col gap-6">
          {/* 入库 */}
          <section>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">新增文档</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {/* 拖拽区：拖进来或点击选择文件 */}
                <div
                  className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-6 py-8 text-center transition-colors ${
                    dragging ? "border-primary bg-primary/5" : "border-input hover:bg-accent/40"
                  }`}
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragging(true)
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setDragging(false)
                    const file = e.dataTransfer.files?.[0]
                    if (file) void onPickFile(file)
                  }}
                >
                  <IconUpload size={22} className="text-muted-foreground" />
                  <p className="text-sm">把 txt / markdown 拖到这里，或点击选择文件</p>
                  <p className="text-muted-foreground text-xs">
                    也可以直接在下面粘贴内容
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) void onPickFile(file)
                      e.target.value = ""
                    }}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <input
                    className="border-input bg-background min-w-[220px] flex-1 rounded-md border px-3 py-2 text-sm"
                    placeholder="文档名，例如 产品手册.md"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                  <input
                    className="border-input bg-background w-44 rounded-md border px-3 py-2 text-sm"
                    placeholder="分块字数（可选）"
                    value={chunkSize}
                    onChange={(e) => setChunkSize(e.target.value)}
                  />
                </div>

                <textarea
                  className="border-input bg-background min-h-[160px] rounded-md border px-3 py-2 font-mono text-sm"
                  placeholder="文档内容"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />

                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground text-xs">
                    分块小一点通常检索更准；留空则用后端默认值（500 字 / 重叠 80）
                  </span>
                  <Button
                    onClick={() => void ingest()}
                    disabled={loading || !name.trim() || !text.trim()}
                  >
                    {loading ? "处理中…" : "入库"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 检索调试 */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold">检索调试</h2>
            <div className="flex items-center gap-2">
              <input
                className="border-input bg-background flex-1 rounded-md border px-3 py-2 text-sm"
                placeholder="输入一个问题，看看会命中哪些片段"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void search()
                }}
              />
              <button
                className="border-input hover:bg-accent rounded-md border px-4 py-2 text-sm disabled:opacity-50"
                onClick={() => void search()}
                disabled={searching || !query.trim()}
              >
                {searching ? "检索中…" : "检索"}
              </button>
            </div>

            {hits !== null && (
              <div className="flex flex-col gap-2">
                {hits.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    没有命中任何片段（说明这个问题在知识库里找不到依据，回答时不会硬凑引用）
                  </p>
                ) : (
                  hits.map((hit) => (
                    <div key={hit.id} className="rounded-md border px-3 py-2 text-sm">
                      <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
                        <span className="font-mono">[{hit.id}]</span>
                        <span>{hit.document_name}</span>
                        <span>第 {hit.chunk_index} 块</span>
                        <span>分数 {hit.score}</span>
                      </div>
                      <p className="whitespace-pre-wrap">{hit.preview}</p>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>

          {/* 文档列表 */}
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold">已有文档（{documents.length}）</h2>
            {documents.length === 0 ? (
              <p className="text-muted-foreground text-sm">还没有文档，先在上面入库一篇。</p>
            ) : (
              <div className="overflow-hidden rounded-md border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-muted-foreground text-xs">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">文档</th>
                      <th className="px-3 py-2 text-right font-medium">字数</th>
                      <th className="px-3 py-2 text-right font-medium">块大小</th>
                      <th className="px-3 py-2 text-left font-medium">嵌入模型</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((document) => (
                      <tr key={document.id} className="border-t">
                        <td className="max-w-[280px] truncate px-3 py-2" title={document.name}>
                          {document.name}
                        </td>
                        <td className="px-3 py-2 text-right">{document.char_count}</td>
                        <td className="px-3 py-2 text-right">{document.chunk_size || "默认"}</td>
                        <td className="px-3 py-2">
                          {document.embedding_model ? (
                            <Badge variant="secondary" className="font-mono text-[11px]">
                              {document.embedding_model}
                              {document.embedding_dim ? ` · ${document.embedding_dim}维` : ""}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            className="hover:bg-destructive/10 text-destructive rounded p-1"
                            title="删除该文档及其分块"
                            onClick={() => setPendingDelete(document)}
                          >
                            <IconTrash size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除这篇文档？</AlertDialogTitle>
            <AlertDialogDescription>
              「{pendingDelete?.name}」及其全部 {pendingDelete ? "分块" : ""}
              会从知识库移除，之后提问不会再引用到它。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const target = pendingDelete
                setPendingDelete(null)
                if (target) void remove(target)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
