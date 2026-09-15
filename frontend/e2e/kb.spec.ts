import { expect, test } from "@playwright/test"
import { expectToast, openClean } from "./helpers"

test.describe("知识库", () => {
  test.beforeEach(async ({ page }) => {
    await openClean(page, "/local/kb")
  })

  test("入库 → 表格 → 搜索 → 排序", async ({ page }) => {
    const suffix = Date.now()
    const shortName = `e2e-short-${suffix}.md`
    const longName = `e2e-long-${suffix}.md`

    const ingest = async (name: string, text: string) => {
      await page.getByPlaceholder(/文档名/).fill(name)
      await page.getByPlaceholder("文档内容").fill(text)
      await page.getByRole("button", { name: "入库", exact: true }).click()
      await expectToast(page, "已入库")
      await expect(page.locator("table")).toContainText(name)
    }

    await ingest(shortName, `短文档 ${suffix}。`)
    await ingest(longName, `长文档 ${suffix}。`.repeat(80))

    // 搜索：只留匹配的行
    await page.getByPlaceholder("按名称搜索文档").fill(`e2e-short-${suffix}`)
    await expect(page.locator("table tbody tr")).toHaveCount(1)
    await expect(page.locator("table")).toContainText(shortName)

    // 清空搜索，按字数排序并验证升降序切换
    await page.getByPlaceholder("按名称搜索文档").fill("")
    await page.getByTitle("按字数排序").click()
    const shortRow = page.locator("table tbody tr").filter({ hasText: shortName })
    const longRow = page.locator("table tbody tr").filter({ hasText: longName })
    const rowIndex = (row: typeof shortRow) =>
      row.evaluate((element) => Array.from(element.parentElement?.children ?? []).indexOf(element))

    // 第一次点击按字数降序，长文档在前
    expect(await rowIndex(longRow)).toBeLessThan(await rowIndex(shortRow))

    // 再点一次切换为升序，短文档在前
    await page.getByTitle("按字数排序").click()
    expect(await rowIndex(shortRow)).toBeLessThan(await rowIndex(longRow))

    // 删除（二次确认）
    await page
      .locator("table tbody tr")
      .filter({ hasText: longName })
      .getByTitle("删除该文档及其分块")
      .click()
    await expect(page.getByRole("alertdialog")).toContainText("删除这篇文档")
    await page.getByRole("button", { name: "删除", exact: true }).click()
    await expectToast(page, "已删除")
    await expect(page.locator("table")).not.toContainText(longName)
  })

  test("检索调试：能命中刚入库的内容", async ({ page }) => {
    const name = `e2e-search-${Date.now()}.md`
    await page.getByPlaceholder(/文档名/).fill(name)
    await page
      .getByPlaceholder("文档内容")
      .fill(`离线优先是一种产品设计原则，网络不可用时依然可用。（${name}）`)
    await page.getByRole("button", { name: "入库", exact: true }).click()
    await expectToast(page, "已入库")

    await page.getByPlaceholder(/输入一个问题/).fill("网络不可用时还能用吗")
    await page.getByRole("button", { name: "检索" }).click()

    await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  })

  test("不支持的格式会被拒绝", async ({ page }) => {
    // 直接打后端的上传接口，验证错误信息可读
    const response = await page.request.post("/api/veyra/documents/upload", {
      multipart: {
        file: {
          name: "photo.png",
          mimeType: "image/png",
          buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47])
        }
      }
    })

    expect(response.status()).toBe(400)
    expect(await response.text()).toContain("暂不支持")
  })
})
