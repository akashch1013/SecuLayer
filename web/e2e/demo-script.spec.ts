import { expect, test, type Locator, type Page } from "@playwright/test";

import { column, guardNetwork } from "./helpers";

const OUTCOME_TIMEOUT = process.env.E2E_LIVE === "1" ? 70_000 : 20_000;

async function activate(page: Page, target: Locator) {
  for (let count = 0; count < 180; count += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) {
      await page.keyboard.press("Enter");
      return;
    }
    await page.keyboard.press("Tab");
  }
  throw new Error(`Keyboard could not reach ${target}`);
}

async function selectCase(page: Page, target: Locator) {
  await activate(page, page.getByRole("listbox").getByRole("option", { selected: true }));
  await page.keyboard.press("Home");
  for (let count = 0; count < 30; count += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) {
      await page.keyboard.press("Enter");
      await expect(target).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("region", { name: "The setup", exact: true })).toHaveCount(1);
      return;
    }
    await page.keyboard.press("ArrowDown");
  }
  throw new Error(`Keyboard could not select ${target}`);
}

test("presenter demo from home to results using the keyboard", async ({ page }) => {
  test.setTimeout(180_000);
  const offsite = await guardNetwork(page);
  await page.goto("/");
  await activate(page, page.getByRole("button", { name: "Large text" }));
  await activate(page, page.getByRole("link", { name: "Start with the inbox assistant" }));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Inbox assistant");
  await activate(page, page.getByRole("switch", { name: "Show what the AI reads" }));
  await page.keyboard.press("u");
  await expect(column(page, "Without SecuLayer").getByTestId("outcome-banner")).toBeVisible({
    timeout: OUTCOME_TIMEOUT,
  });
  await page.keyboard.press("p");
  await expect(page.getByRole("region", { name: "What the model received" })).toBeFocused();
  await page.keyboard.press("s");
  await expect(column(page, "With SecuLayer").getByTestId("outcome-banner")).toBeVisible({
    timeout: OUTCOME_TIMEOUT,
  });

  await activate(page, page.getByTestId("layer-menu"));
  for (const name of ["Hidden-text cleaner", "Screening", "Prompt hardening", "Output guard"]) {
    const toggle = page.getByRole("switch", { name, exact: true });
    await activate(page, toggle);
  }
  await page.keyboard.press("Escape");
  await page.keyboard.press("s");
  await expect(column(page, "With SecuLayer").getByTestId("outcome-banner")).toBeVisible({
    timeout: OUTCOME_TIMEOUT,
  });

  await selectCase(page, page.getByRole("option", { name: /The polite invoice/ }));
  await page.keyboard.press("s");
  const dialog = page.getByRole("dialog", { name: "SecuLayer paused an action" });
  const protectedColumn = column(page, "With SecuLayer");
  await expect(protectedColumn.getByTestId("outcome-banner").or(dialog).first()).toBeVisible({
    timeout: OUTCOME_TIMEOUT,
  });
  // In the real recordings trial 1 blocks; trial 2 asks for approval. The fixture asks in 1.
  if (!(await dialog.isVisible()) && !process.env.E2E_LIVE) {
    await activate(page, protectedColumn.getByRole("button", { name: "Next recorded run" }));
    await expect(dialog).toBeVisible({ timeout: 20_000 });
  }
  if (await dialog.isVisible()) {
    await expect(dialog.getByRole("button", { name: "Don't send" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeHidden();
  }

  await activate(page, page.getByRole("link", { name: "All scenarios", exact: true }));
  await activate(page, page.getByRole("link", { name: /HelpDesk/ }).first());
  await selectCase(page, page.getByRole("option", { name: /The fake policy/ }));
  for (const [key, name] of [
    ["u", "Without SecuLayer"],
    ["s", "With SecuLayer"],
  ] as const) {
    await page.keyboard.press(key);
    await expect(column(page, name).getByTestId("outcome-banner")).toBeVisible({ timeout: OUTCOME_TIMEOUT });
  }
  await activate(
    page,
    page
      .getByRole("navigation", { name: "Main" })
      .getByRole("link", { name: "Results", exact: true }),
  );
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Results");
  expect(offsite).toEqual([]);
});
