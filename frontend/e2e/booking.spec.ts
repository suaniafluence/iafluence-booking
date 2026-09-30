import { expect, test } from "@playwright/test";
import { arriveFromStripe, customerEmail, openSlotPicker, summaryValue, timeButtons } from "./helpers";

test.describe("réservation client", () => {
  test("du retour Stripe au rendez-vous confirmé @mobile", async ({ page }) => {
    const who = await arriveFromStripe(page, 5);
    const bookingUrl = page.url();

    await expect(page.getByRole("heading", { name: "Votre conseil IA est confirmé" })).toBeVisible();
    await expect(summaryValue(page, "Heures achetées")).toHaveText("5 h");
    await expect(summaryValue(page, "Heures restantes après cette session")).toHaveText("4 h");

    // Privacy (R05): the browser only ever receives start/end, never calendar details.
    const availability = page.waitForResponse((r) => r.url().includes("/api/availability"));
    await openSlotPicker(page);
    const { slots } = await (await availability).json();
    expect(slots.length).toBeGreaterThan(0);
    for (const s of slots) expect(Object.keys(s).sort()).toEqual(["end", "start"]);

    const day = await page.getByRole("heading", { level: 2 }).textContent();
    const slot = timeButtons(page).first();
    const time = (await slot.textContent())!;
    await slot.click();

    await expect(page.getByRole("heading", { name: "Votre rendez-vous" })).toBeVisible();
    await expect(page.getByText(new RegExp(`^${day}`))).toBeVisible();
    await expect(page.getByText(new RegExp(`^${time} - `))).toBeVisible();
    await expect(page.getByText(customerEmail(who))).toBeVisible();
    await page.getByRole("button", { name: "Confirmer le rendez-vous" }).click();

    await expect(page.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();
    await expect(page.getByText(new RegExp(`^${time} - .* · Conseil IA avec Suan Tay$`))).toBeVisible();
    await expect(page.getByRole("link", { name: /^https:\/\/meet\.google\.com\// })).toBeVisible();
    await expect(summaryValue(page, "Heures achetées")).toHaveText("5 h");
    await expect(summaryValue(page, "Heures planifiées")).toHaveText("1 h");
    await expect(summaryValue(page, "Heures restantes")).toHaveText("4 h");

    // Persisted: coming back to the link shows the booking, not the picker.
    await page.reload();
    await expect(page.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();
    await expect(page.getByText(new RegExp(`^${time} - `))).toBeVisible();

    // Replaying the Stripe redirect is idempotent: same booking link.
    await page.goto(`/reservation?session_id=cs_demo_5h_${who}`);
    await expect(page).toHaveURL(bookingUrl);
    await expect(page.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();
  });

  test("deux clients sur le même créneau : un seul l'obtient", async ({ page, context }) => {
    const other = await context.newPage();
    await arriveFromStripe(page, 2);
    await arriveFromStripe(other, 1);
    await openSlotPicker(page);
    await openSlotPicker(other);

    const day = await page.getByRole("heading", { level: 2 }).textContent();
    await expect(other.getByRole("heading", { level: 2 })).toHaveText(day!);
    const time = (await timeButtons(page).first().textContent())!;
    await timeButtons(page).first().click();
    await other.getByRole("button", { name: time, exact: true }).click();

    await page.getByRole("button", { name: "Confirmer le rendez-vous" }).click();
    await expect(page.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();

    await other.getByRole("button", { name: "Confirmer le rendez-vous" }).click();
    await expect(other.getByRole("heading", { name: "Choisissez votre créneau" })).toBeVisible();
    await expect(other.getByRole("alert")).toHaveText(
      "Ce créneau vient d’être réservé ou n’est plus disponible. Veuillez choisir un autre horaire.",
    );
    // The fresh list no longer offers the slot taken by the first customer.
    await expect(other.getByRole("tablist")).toBeVisible();
    if ((await other.getByRole("heading", { level: 2 }).textContent()) === day) {
      await expect(other.getByRole("button", { name: time, exact: true })).toHaveCount(0);
    }
    // The losing customer can still book another slot.
    await timeButtons(other).first().click();
    await other.getByRole("button", { name: "Confirmer le rendez-vous" }).click();
    await expect(other.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();
    await expect(summaryValue(other, "Heures restantes")).toHaveText("0 h");
  });

  test("changer d'avis avant de confirmer", async ({ page }) => {
    await arriveFromStripe(page, 3);
    await openSlotPicker(page);
    const tabs = page.getByRole("tab");
    if ((await tabs.count()) > 1) {
      await tabs.nth(1).click();
      await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
    }
    await timeButtons(page).last().click();
    await page.getByRole("button", { name: "Changer de créneau" }).click();
    await expect(page.getByRole("heading", { name: "Choisissez votre créneau" })).toBeVisible();

    await page.reload();
    await expect(page.getByRole("heading", { name: "Votre conseil IA est confirmé" })).toBeVisible();
  });
});

test.describe("liens invalides", () => {
  test("lien de réservation inconnu", async ({ page }) => {
    await page.goto("/reservation/nimporte-quoi");
    await expect(page.getByRole("heading", { name: "Lien de réservation indisponible" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveText("Ce lien de réservation est invalide ou a expiré.");
  });

  test("paiement inconnu au retour de Stripe", async ({ page }) => {
    await page.goto("/reservation?session_id=cs_live_inconnu");
    await expect(page.getByRole("heading", { name: "Nous n’avons pas pu vérifier votre paiement" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveText("Paiement introuvable ou non finalisé.");
    await page.getByRole("button", { name: "Réessayer" }).click();
    await expect(page.getByRole("alert")).toHaveText("Paiement introuvable ou non finalisé.");
  });

  test("retour Stripe sans identifiant de paiement", async ({ page }) => {
    await page.goto("/reservation");
    await expect(page.getByRole("alert")).toHaveText("Lien incomplet : identifiant de paiement manquant.");
    await expect(page.getByRole("button", { name: "Réessayer" })).toHaveCount(0);
  });

  test("page inconnue", async ({ page }) => {
    await page.goto("/tarifs");
    await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
    await expect(page.getByRole("link", { name: "iafluence.fr" })).toHaveAttribute("href", "https://iafluence.fr");
  });

  test("webhook Stripe non signé refusé", async ({ request }) => {
    const r = await request.post("/webhooks/stripe", { data: { id: "evt_forged", type: "charge.refunded" } });
    expect(r.status()).toBe(400);
  });
});
