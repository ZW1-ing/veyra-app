"use client"

import {
  DEFAULT_SETTINGS,
  backendRequestHeaders,
  loadSettings,
  saveSettings,
  type LocalSettings
} from "@/lib/local-chat/settings"
import { useCallback, useEffect, useState } from "react"

/**
 * 本地模式设置。
 *
 * 后端地址与密钥存在浏览器里，随请求头发给 Next 的代理路由；
 * 代理只接受本机地址（127.0.0.1 / localhost），避免变成 SSRF 跳板。
 */

const MODELS = [
  { id: "veyra-agent", label: "Veyra 智能体（带工具）" },
  { id: "veyra-swarm", label: "Veyra 蜂群（多智能体）" }
]

export default function LocalSettingsPage() {
  const [settings, setSettings] = useState<LocalSettings>(DEFAULT_SETTINGS)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [health, setHealth] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    setSettings(loadSettings())
  }, [])

  const persist = useCallback((next: LocalSettings) => {
    setSettings(next)
    saveSettings(next)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }, [])

  const test = useCallback(async () => {
    setTesting(true)
    setHealth("")
    setError("")
    try {
      const response = await fetch("/api/veyra/health", {
        headers: backendRequestHeaders(settings),
        cache: "no-store"
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.message || `HTTP ${response.status}`)
      setHealth(`连接正常：数据库 ${body.database}，模型后端 ${body.provider} / ${body.model}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : "连接失败")
    } finally {
      setTesting(false)
    }
  }, [settings])

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="border-b px-6 py-3">
        <h1 className="text-base font-semibold">设置</h1>
        <p className="text-muted-foreground text-xs">
          这些配置只保存在这台浏览器里，用来决定前端连哪个后端
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-2xl flex-col gap-5">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">后端地址</span>
            <input
              className="border-input bg-background rounded-md border px-3 py-2 text-sm"
              value={settings.backendUrl}
              onChange={(e) => setSettings({ ...settings, backendUrl: e.target.value })}
              placeholder="http://127.0.0.1:8000"
            />
            <span className="text-muted-foreground text-xs">
              只允许本机地址（127.0.0.1 / localhost）；服务在别的机器上时，请用环境变量
              VEYRA_API_URL 配置，并自行处理网络暴露与鉴权。
            </span>
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">API Key</span>
            <input
              className="border-input bg-background rounded-md border px-3 py-2 text-sm"
              value={settings.apiKey}
              onChange={(e) => setSettings({ ...settings, apiKey: e.target.value })}
              placeholder="后端没配 API_KEYS 时留空"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">新会话默认模式</span>
            <select
              className="border-input bg-background rounded-md border px-3 py-2 text-sm"
              value={settings.defaultModel}
              onChange={(e) => setSettings({ ...settings, defaultModel: e.target.value })}
            >
              {MODELS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-center gap-3">
            <button
              className="bg-primary text-primary-foreground rounded-md px-4 py-2 text-sm"
              onClick={() => persist(settings)}
            >
              保存
            </button>
            <button
              className="border-input hover:bg-accent rounded-md border px-4 py-2 text-sm disabled:opacity-50"
              onClick={() => void test()}
              disabled={testing}
            >
              {testing ? "测试中…" : "测试连接"}
            </button>
            <button
              className="text-muted-foreground hover:text-foreground text-sm underline"
              onClick={() => persist(DEFAULT_SETTINGS)}
            >
              恢复默认
            </button>
            {saved && <span className="text-sm text-emerald-600 dark:text-emerald-400">已保存</span>}
          </div>

          {health && (
            <div className="rounded-md border border-emerald-500/40 px-3 py-2 text-sm text-emerald-600 dark:text-emerald-400">
              {health}
            </div>
          )}
          {error && (
            <div className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
