import { expect, test } from "@playwright/test";

test("paste a link, watch it inspect, download the file", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("Video link").fill("https://video.example/watch/1");
  await page.getByRole("button", { name: "Fetch" }).click();

  await expect(page.getByRole("heading", { name: "A short film" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /720p/ })).toBeChecked();

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).click();
  const download = await downloading;

  expect(download.suggestedFilename()).toBe("A short film (720p).mp4");
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(chunk as Buffer);
  expect(Buffer.concat(chunks).toString()).toBe("movie-bytes");
});
