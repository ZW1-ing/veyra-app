import { defineConfig, devices } from "@playwright/test"
import { existsSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

/**
 * E2E 配置。
 *
 * 两个 webServer 一起拉起来：后端用 mock 模型 + SQLite（不依赖 Ollama 与 MySQL，
 * 保证 CI 上可重复），前端起在 3100 端口并通过 VEYRA_API_URL 指向它。
 */

const BACKEND_DIR = join(__dirname, "..", "backend")
const PYTHON =
  process.env.E2E_PYTHON ??
  (process.platform === "win32"
    ? join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
    : join(BACKEND_DIR, ".venv", "bin", "python"))

// 本机缓存的 Chromium 版本可能和当前 Playwright 期望的不一致，允许用环境变量指定
const CHROME = process.env.E2E_CHROME_PATH

const BACKEND_PORT = 8010
const FRONTEND_PORT = 3100
// 每次 E2E 都从空数据库开始：旧库可能还是升级前的 schema，create_all 不会补列
const E2E_DB_PATH = join(tmpdir(), `veyra-e2e-${process.pid}.db`)
const E2E_DATABASE_URL = `sqlite+pysqlite:///${E2E_DB_PATH.replaceAll("\\", "/")}`
rmSync(E2E_DB_PATH, { force: true })

// 暴露给测试用例：前端设置页里的后端地址会以请求头形式覆盖环境变量，
// 所以 E2E 必须显式把 localStorage 里的地址指到测试后端，否则会打到开发者本机的服务
process.env.E2E_BACKEND_URL = process.env.E2E_BACKEND_URL ?? `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  testDir: "./e2e",
  // 共用一个后端与数据库，串行跑避免互相污染
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    launchOptions: CHROME ? { executablePath: CHROME } : {},
    permissions: ["clipboard-read", "clipboard-write"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${PYTHON}" -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: BACKEND_DIR,
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        // 用 SQLite 与 mock 模型：E2E 不该依赖 MySQL / Ollama
        DATABASE_URL: E2E_DATABASE_URL,
        LLM_PROVIDER: "mock",
        EMBEDDING_PROVIDER: "hash",
        EMBEDDING_DIM: "128",
        AGENT_MAX_STEPS: "3",
        RATE_LIMIT_PER_MINUTE: "0",
        MODEL_PRICES:
          '{"mock-assistant":{"prompt_per_million":1,"completion_per_million":2}}',
        TENANT_QUOTAS:
          '{"anonymous":{"daily_tokens":100000,"daily_cost":1,"model_tokens":{"mock-assistant":50000}}}'
      }
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        NEXT_TELEMETRY_DISABLED: "1",
        VEYRA_API_URL: `http://127.0.0.1:${BACKEND_PORT}`
      }
    }
  ]
})

// 本机缺虚拟环境时给出明确提示，而不是让 Playwright 报「webServer 超时」
if (!existsSync(PYTHON) && !process.env.CI && !process.env.E2E_PYTHON) {
  console.warn(
    `[e2e] 没找到后端虚拟环境：${PYTHON}\n      先执行：cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`
  )
}
