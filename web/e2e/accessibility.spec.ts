import { expect, test } from "@playwright/test";

import { expectCleanAxe, guardNetwork, SCREENSHOTS } from "./helpers";

const SCREENS = [
  ["/", "home"],
  ["/lab", "scenarios"],
  ["/lab/inbox", "inbox"],
  ["/lab/support", "support"],
  ["/lab/page", "page"],
  ["/lab/helpdesk", "helpdesk"],
  ["/how", "how"],
  ["/results", "results"],
  ["/limits", "limits"],
  ["/sandbox", "sandbox"],
  ["/sources", "sources"],
  ["/missing", "not-found"],
];

for (const size of ["normal", "large"] as const) {
  test(`every screen: ${size} text, reduced motion, axe and layout`, async ({ page }) => {
    test.setTimeout(180_000);
    const offsite = await guardNetwork(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript((textSize) => {
      localStorage.setItem("seculayer.textSize", textSize);
    }, size);
    for (const [path, name] of SCREENS) {
      await page.goto(path!);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectCleanAxe(page);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
        `${name} fits the viewport at ${size} text`,
      ).toBe(true);
      expect(
        await page.evaluate(() =>
          parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue("--duration-reveal"),
          ),
        ),
      ).toBe(0);
      if (await page.locator("iframe").count()) {
        // Chrome paints offscreen sandbox frames after they enter the viewport.
        await page.locator("iframe").first().scrollIntoViewIfNeeded();
      }
      await page.screenshot({
        path: `${SCREENSHOTS}m9-${name}-${page.viewportSize()?.width}-${size}.png`,
        fullPage: true,
      });
    }
    expect(offsite).toEqual([]);
  });
}

test("navigation moves focus into the new page", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Limits" })
    .click();
  await expect(page.locator("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("main :focus")).toBeVisible();
});
