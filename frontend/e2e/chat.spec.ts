import { expect, test } from "@playwright/test"
import { expectToast, openClean } from "./helpers"

test.describe("会话", () => {
  test.beforeEach(async ({ page }) => {
    await openClean(page, "/local")
  })

  test("空状态 → 发消息 → 复制 → 重新生成", async ({ page }) => {
    await expect(page.getByText("开始一段新对话")).toBeVisible()

    await page.getByPlaceholder(/输入问题/).fill("你好，Veyra")
    await page.getByRole("button", { name: "发送" }).click()

    // mock 模型会把提问复述回来，据此确认整条链路通了
    await expect(page.locator("main")).toContainText("[mock] 收到：你好，Veyra")

    // 悬停消息出现操作
    const lastMessage = page.locator("main .group\\/message").last()
    await lastMessage.hover()
    await page.getByTitle("复制这条消息").last().click()
    await expectToast(page, "已复制到剪贴板")
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe("[mock] 收到：你好，Veyra")

    // 重新生成：回答被替换，但用户消息不变
    await lastMessage.hover()
    await page.getByTitle("用同一个提问重新生成").last().click()
    await expect(page.locator("main")).toContainText("[mock] 收到：你好，Veyra")
    await expect(page.locator("main .group\\/message")).toHaveCount(2)
  })

  test("Enter 发送，Shift+Enter 换行", async ({ page }) => {
    const input = page.getByPlaceholder(/输入问题/)
    await input.click()
    await page.keyboard.type("第一行")
    await page.keyboard.down("Shift")
    await page.keyboard.press("Enter")
    await page.keyboard.up("Shift")
    await page.keyboard.type("第二行")

    await expect(input).toHaveValue("第一行\n第二行")
    await page.keyboard.press("Enter")
    await expect(page.locator("main")).toContainText("第一行")
  })
})
