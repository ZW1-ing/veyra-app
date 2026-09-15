import { expect, type Page } from "@playwright/test"

/**
 * 等客户端接管页面。
 *
 * 导航栏的主题按钮在挂载后标题会从「主题」变成「切到亮色/暗色」，
 * 用它当水合完成的信号：不等的话，点击与输入会被 SSR 出来的空壳吞掉。
 */
export async function waitForHydration(page: Page): Promise<void> {
  await page.locator('button[title^="切到"]').waitFor({ timeout: 60_000 })
}

/**
 * 打开本地模式的某一页，并把本地状态重置成「干净且指向测试后端」。
 *
 * 用 addInitScript 在页面脚本之前写入：前端把设置里的后端地址放进请求头，
 * 会覆盖服务端的环境变量，所以这里必须显式指到测试后端（默认 8010）。
 */
export async function openClean(page: Page, path: string): Promise<void> {
  const backendUrl = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:8010"
  await page.addInitScript((url) => {
    localStorage.removeItem("veyra-local-sessions-v1")
    localStorage.removeItem("veyra-local-assistants-v1")
    localStorage.setItem(
      "veyra-local-settings-v1",
      JSON.stringify({ backendUrl: url, apiKey: "", defaultModel: "veyra-agent" })
    )
  }, backendUrl)

  await page.goto(path)
  await waitForHydration(page)
}

/** 等一条 toast 出现（组件库里是 sonner） */
export async function expectToast(page: Page, text: string | RegExp): Promise<void> {
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: text }).first()).toBeVisible()
}
