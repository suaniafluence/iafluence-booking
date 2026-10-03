import { expect, test } from "@playwright/test";
import { bookedCustomer, connectCodex, consultantLogin, customerEmail, customerName, endSessionsOf, outbox } from "./helpers";

// Demo mode: Fireflies has a recording of every session, the demo agent writes the summary and the infographic,
// Gmail drafts are saved as .eml files. The end-of-session and report jobs run every second.
test("séance terminée → brouillon Gmail avec la synthèse et l'infographie", async ({ page, request }) => {
  const who = await bookedCustomer(request, 2);
  // Codex must be connected before the session ends (otherwise the report fails and the admin is alerted).
  const codex = await connectCodex(page);

  endSessionsOf(customerEmail(who));
  await consultantLogin(page);

  const reports = page.locator("section").filter({ has: page.getByRole("heading", { name: "Comptes rendus de séance" }) });
  const item = reports.getByRole("listitem").filter({ hasText: customerName(who) }).first();
  await expect(async () => {
    await page.reload();
    await expect(item).toContainText("Brouillon créé avec compte rendu", { timeout: 1_000 });
  }).toPass({ timeout: 30_000 });

  // Preview: the summary and the PNG rendered by the server.
  await item.getByRole("button", { name: `Aperçu du compte rendu de ${customerName(who)}` }).click();
  await expect(item.getByRole("heading", { name: "Points abordés" })).toBeVisible();
  await expect(item.getByText("Rassembler dix exemples de devis représentatifs")).toBeVisible();
  const image = item.getByRole("img", { name: `Infographie de la séance de ${customerName(who)}` });
  await expect(image).toBeVisible();
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1200);

  // The Gmail draft: text + HTML with the infographic inline (cid:), then the link to book the next session.
  const drafts = () => outbox().filter((m) => m.to === customerEmail(who) && m.kind === "draft");
  const [draft] = drafts();
  expect(draft.subject).toBe("Compte rendu de votre session et réservation de la suivante");
  expect(draft.parts).toEqual(["multipart/alternative", "text/plain", "multipart/related", "text/html", "image/png"]);
  expect(draft.cids).toEqual(["<compte-rendu>"]);
  expect(draft.html).toContain('src="cid:compte-rendu"');
  expect(draft.text).toContain(`Bonjour ${customerName(who)},`);
  expect(draft.text).toContain("Vos actions\n- Rassembler dix exemples de devis représentatifs");
  expect(draft.text).toMatch(/Il vous reste 1 heure de conseil\.[^]*\/reservation\/[A-Za-z0-9_-]{43}\n/);

  // One draft only, however many times the jobs run.
  await page.waitForTimeout(3_000);
  expect(drafts()).toHaveLength(1);
});
