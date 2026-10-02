import { expect, test } from "@playwright/test";

const PAGES = [
  ["/", "Video link"],
  ["/terms", "Terms of use"],
  ["/privacy", "Privacy"],
  ["/sites", "Supported sites"],
  ["/report", "Report content"],
] as const;

test.use({ viewport: { width: 375, height: 800 } });

for (const [path, marker] of PAGES) {
  test(`${path} fits a phone screen without sideways scrolling`, async ({ page }) => {
    await page.goto(path);
    if (path === "/") await expect(page.getByLabel(marker)).toBeVisible();
    else await expect(page.getByRole("heading", { name: marker, level: 2 })).toBeVisible();
    if (path === "/sites") await expect(page.getByText(/ of \d+ sites/)).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("the report form is addressed to the operator", async ({ page }) => {
  await page.goto("/report");
  await expect(page.getByText(/addressed to takedown@fetchall\.example/)).toBeVisible();
});
