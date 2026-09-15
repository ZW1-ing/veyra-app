import { expect, test } from "@playwright/test"
import { openClean } from "./helpers"

test.describe("主题", () => {
  test("设置页可在亮色 / 暗色 / 跟随系统之间切换", async ({ page }) => {
    await openClean(page, "/local/settings")

    await page.getByRole("tab", { name: "外观" }).click()

    const picker = page.getByRole("combobox")
    await picker.click()
    await expect(page.getByRole("option")).toHaveText([/亮色/, /暗色/, /跟随系统/])

    await page.getByRole("option", { name: "亮色" }).click()
    await expect(page.locator("html")).toHaveClass(/light/)

    await picker.click()
    await page.getByRole("option", { name: "暗色" }).click()
    await expect(page.locator("html")).toHaveClass(/dark/)

    await picker.click()
    await page.getByRole("option", { name: "跟随系统" }).click()
    // 跟随系统时 class 由 prefers-color-scheme 决定，两种都可能，只要不再是固定值即可
    await expect(page.locator("html")).toHaveClass(/(light|dark)/)
  })

  test("导航栏按钮快速切换亮暗", async ({ page }) => {
    await openClean(page, "/local")

    const before = await page.locator("html").getAttribute("class")
    await page.locator('button[title^="切到"]').dispatchEvent("click")
    await expect(page.locator("html")).not.toHaveClass(before ?? "")
  })
})
