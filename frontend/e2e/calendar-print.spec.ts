import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { adminLogin } from "./helpers";

test("l'administrateur télécharge son calendrier en PDF sur une période", async ({ page }) => {
  await adminLogin(page);
  const section = page.locator("section").filter({ has: page.getByRole("heading", { name: "Imprimer mon calendrier" }) });
  await expect(section.getByLabel("Du")).toHaveValue(/^\d{4}-\d\d-\d\d$/);

  await section.getByLabel("Du").fill("2026-10-05");
  await section.getByLabel("Au").fill("2026-10-04");
  await section.getByRole("button", { name: "Télécharger le PDF" }).click();
  await expect(section.getByRole("alert")).toHaveText("La date de fin doit être le même jour ou après la date de début.");

  await section.getByLabel("Au").fill("2026-10-18");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    section.getByRole("button", { name: "Télécharger le PDF" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("calendrier-2026-10-05-au-2026-10-18.pdf");
  const pdf = readFileSync((await download.path())!);
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.toString("latin1").match(/\/Type \/Page\b/g)).toHaveLength(2); // one page per week
  await expect(section.getByRole("alert")).toHaveCount(0);
});
