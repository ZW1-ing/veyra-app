"use client"

import { backendRequestHeaders, loadSettings } from "@/lib/local-chat/settings"
import { IconRefresh } from "@tabler/icons-react"
import { useCallback, useEffect, useState } from "react"

/**
 * 用量统计。
 *
 * 后端每次对话都会把 token 用量写进 usage_records，这一页把它变成能看的东西：
 * 总调用、总 token、按模型的分布与按天的趋势。
 */

interface UsageBucket {
  key: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
}

interface UsageSummary {
  total_calls: number
  total_tokens: number
  prompt_tokens: number
  completion_tokens: number
  days: number
  total_cost: number
  pricing_configured: boolean
  by_day: UsageBucket[]
  by_model: UsageBucket[]
}

function formatNumber(value: number): string {
  return value.toLocaleString("zh-CN")
}

function formatCost(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 0.01 ? 4 : 2,
    maximumFractionDigits: 4
  }).format(value)
}

export default function UsagePage() {
  const [days, setDays] = useState(14)
  const [data, setData] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const response = await fetch(`/api/veyra/usage?days=${days}`, {
        headers: backendRequestHeaders(loadSettings()),
        cache: "no-store"
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || `加载失败（HTTP ${response.status}）`)
      setData(body as UsageSummary)
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const maxDayTokens = Math.max(1, ...(data?.by_day.map((d) => d.total_tokens) ?? [1]))
  const maxModelTokens = Math.max(1, ...(data?.by_model.map((m) => m.total_tokens) ?? [1]))

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <div>
          <h1 className="text-base font-semibold">用量统计</h1>
          <p className="text-muted-foreground text-xs">
            每次对话的 token 用量都落在本机数据库里，这里按模型与日期聚合
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="border-input bg-background rounded-md border px-3 py-1.5 text-sm"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[7, 14, 30, 90].map((d) => (
              <option key={d} value={d}>
                最近 {d} 天
              </option>
            ))}
          </select>
          <button
            className="border-input hover:bg-accent flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            刷新
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-4xl flex-col gap-6">
          {error && (
            <div className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
              {error}
            </div>
          )}

          {data && (
            <>
              {/* 汇总 */}
              <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                {[
                  { label: "调用次数", value: formatNumber(data.total_calls) },
                  { label: "总 token", value: formatNumber(data.total_tokens) },
                  { label: "输入 token", value: formatNumber(data.prompt_tokens) },
                  { label: "输出 token", value: formatNumber(data.completion_tokens) },
                  {
                    label: "估算费用",
                    value: data.pricing_configured ? formatCost(data.total_cost) : "未配置"
                  }
                ].map((item) => (
                  <div key={item.label} className="rounded-md border px-3 py-2.5">
                    <div className="text-muted-foreground text-xs">{item.label}</div>
                    <div className="mt-1 text-lg font-semibold tabular-nums">{item.value}</div>
                  </div>
                ))}
              </section>

              {data.total_calls === 0 && (
                <p className="text-muted-foreground text-sm">
                  还没有记录。去会话页问一句，这里就会有数据。
                </p>
              )}

              {/* 按模型 */}
              {data.by_model.length > 0 && (
                <section className="flex flex-col gap-3">
                  <h2 className="text-sm font-semibold">按模型</h2>
                  <div className="flex flex-col gap-2">
                    {data.by_model.map((item) => (
                      <div key={item.key} className="flex items-center gap-3 text-sm">
                        <span className="w-40 shrink-0 truncate" title={item.key}>
                          {item.key || "（未记录）"}
                        </span>
                        <div className="bg-muted h-2 flex-1 overflow-hidden rounded-full">
                          <div
                            className="bg-primary h-full rounded-full"
                            style={{ width: `${Math.max(2, (item.total_tokens / maxModelTokens) * 100)}%` }}
                          />
                        </div>
                        <span className="text-muted-foreground w-32 shrink-0 text-right tabular-nums">
                          {formatNumber(item.total_tokens)} token · {item.calls} 次
                          {data.pricing_configured ? ` · ${formatCost(item.cost)}` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* 按天 */}
              {data.by_day.length > 0 && (
                <section className="flex flex-col gap-3">
                  <h2 className="text-sm font-semibold">按天</h2>
                  <div className="flex h-40 items-end gap-2 rounded-md border px-4 py-3">
                    {data.by_day.map((item) => (
                      <div
                        key={item.key}
                        className="group flex h-full flex-1 flex-col items-center justify-end gap-1"
                        title={`${item.key}：${item.total_tokens} token / ${item.calls} 次`}
                      >
                        <span className="text-muted-foreground text-[10px] tabular-nums opacity-0 group-hover:opacity-100">
                          {formatNumber(item.total_tokens)}
                        </span>
                        <div
                          className="bg-primary/80 hover:bg-primary w-full rounded-t"
                          style={{ height: `${Math.max(3, (item.total_tokens / maxDayTokens) * 100)}%` }}
                        />
                        <span className="text-muted-foreground text-[10px]">
                          {item.key.slice(5)}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* 明细表 */}
              {data.by_model.length > 0 && (
                <section className="flex flex-col gap-3">
                  <h2 className="text-sm font-semibold">明细</h2>
                  <div className="overflow-hidden rounded-md border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 text-muted-foreground text-xs">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">模型</th>
                          <th className="px-3 py-2 text-right font-medium">调用</th>
                          <th className="px-3 py-2 text-right font-medium">输入 token</th>
                          <th className="px-3 py-2 text-right font-medium">输出 token</th>
                          <th className="px-3 py-2 text-right font-medium">估算费用</th>
                          <th className="px-3 py-2 text-right font-medium">合计</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_model.map((item) => (
                          <tr key={item.key} className="border-t">
                            <td className="px-3 py-2">{item.key || "（未记录）"}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{item.calls}</td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {formatNumber(item.prompt_tokens)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {formatNumber(item.completion_tokens)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {data.pricing_configured ? formatCost(item.cost) : "—"}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {formatNumber(item.total_tokens)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}

          {!data && loading && <p className="text-muted-foreground text-sm">加载中…</p>}
        </div>
      </div>
    </div>
  )
}
