import { expect, test } from "@playwright/test"
import { openClean, waitForHydration } from "./helpers"

test.describe("用量", () => {
  test("对话后能展示 token 与估算费用", async ({ page }) => {
    await openClean(page, "/local")

    await page.getByPlaceholder(/输入问题/).fill("统计这一次的用量")
    await page.getByRole("button", { name: "发送" }).click()
    await expect(page.locator("main")).toContainText("[mock] 收到：统计这一次的用量")

    await page.getByRole("link", { name: "用量" }).click()
    await expect(page).toHaveURL(/\/local\/usage$/)
    await waitForHydration(page)

    await expect(page.getByText("估算费用").first()).toBeVisible()
    await expect(page.getByText(/\$\d/).first()).toBeVisible()
    await expect(page.getByText("今日额度")).toBeVisible()
    await expect(page.getByText("每日 token")).toBeVisible()
    await expect(page.getByText("未配置")).toBeHidden()
  })
})
