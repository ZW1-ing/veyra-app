import { expect, test } from "@playwright/test"
import { openClean } from "./helpers"

test.describe("快捷键与命令面板", () => {
  test.beforeEach(async ({ page }) => {
    await openClean(page, "/local")
  })

  test("Ctrl+N 新建会话", async ({ page }) => {
    const sessions = page.locator("aside div.group")
    await expect(sessions).toHaveCount(1)

    await page.keyboard.press("Control+n")
    await expect(sessions).toHaveCount(2)
  })

  test("Ctrl+K 打开命令面板并搜索", async ({ page }) => {
    await page.keyboard.press("Control+k")

    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText("新建会话")
    await expect(dialog).toContainText("知识库")

    // 输入即过滤：只剩匹配的条目
    await page.keyboard.type("设置")
    await expect(dialog).toContainText("设置")
    await expect(dialog).not.toContainText("知识库")

    await page.keyboard.press("Escape")
    await expect(dialog).toBeHidden()
  })

  test("命令面板里能跳到知识库页", async ({ page }) => {
    await page.keyboard.press("Control+k")
    await page.getByRole("option", { name: /知识库/ }).click()
    await expect(page).toHaveURL(/\/local\/kb$/)
  })
})
