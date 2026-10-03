import { expect, test } from "@playwright/test";
import { ADMIN_PASSWORD } from "./env.mjs";
import { customerEmail, customerName, newCustomer } from "./helpers";


test("le consultant se connecte avec Google, suit les clients et se déconnecte", async ({ page, request }) => {
  // A customer who paid 2 h and booked the first session (through the public API).
  const who = newCustomer();
  const { token } = await (await request.get(`/api/checkout/cs_demo_2h_${who}`)).json();
  const { slots } = await (await request.get(`/api/availability?token=${token}`)).json();
  const booked = await request.post("/api/bookings", { data: { token, start: slots[0].start } });
  expect(booked.status()).toBe(201);

  // The base URL offers the two areas.
  await page.goto("/");
  await page.getByRole("link", { name: /Espace consultant/ }).click();
  await expect(page.getByRole("heading", { name: "Espace consultant" })).toBeVisible();
  // No password for the cockpit: Google only.
  await expect(page.getByLabel("Mot de passe de secours")).toHaveCount(0);
  await page.getByRole("link", { name: "Se connecter avec Google" }).click();
  await expect(page.getByRole("heading", { name: "Cockpit consultant" })).toBeVisible();
  await expect(page.getByRole("link").filter({ hasText: customerName(who) })).toContainText("2 séances restantes");

  const row = page.getByRole("row").filter({ hasText: customerEmail(who) });
  await expect(row.getByRole("cell")).toHaveText([
    `${customerName(who)}${customerEmail(who)}`,
    "Conseil IA - 2h",
    "2 hModifier",
    "1 h",
    "1 h",
    /^\p{Lu}\p{Ll}+ \d{1,2} \p{Ll}+ \d{4} · \d\d:\d\d$/u,
    "",
    "Copier le lien",
  ]);
  const upcoming = page.locator("section").filter({ has: page.getByRole("heading", { name: "Prochains rendez-vous" }) });
  await expect(upcoming.getByRole("listitem").filter({ hasText: customerName(who) })).toBeVisible();

  // Next-session link: drafted by default, sent automatically once ticked — the choice is saved.
  const autoSend = page.getByRole("checkbox", { name: `Envoi automatique pour ${customerName(who)}` });
  await expect(autoSend).not.toBeChecked();
  await autoSend.check();
  await expect(autoSend).toBeChecked();

  // A client who paid outside the website, added by hand.
  const manual = newCustomer();
  await page.getByRole("button", { name: "Ajouter un client" }).click();
  await page.getByLabel("Nom", { exact: true }).fill(customerName(manual));
  await page.getByLabel("Email", { exact: true }).fill(customerEmail(manual));
  await page.getByLabel("Heures achetées").fill("3");
  await page.getByLabel("Montant payé (€)").fill("300");
  await page.getByRole("button", { name: "Ajouter le client" }).click();
  await expect(page.getByRole("alert")).toContainText("Client ajouté. Lien de réservation : http");
  const manualRow = page.getByRole("row").filter({ hasText: customerEmail(manual) });
  await expect(manualRow.getByRole("cell").nth(1)).toHaveText("Conseil IAmanuel");
  await expect(manualRow.getByRole("cell").nth(2)).toHaveText("3 hModifier");

  // The session cookie survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Cockpit consultant" })).toBeVisible();
  await expect(autoSend).toBeChecked();

  // Moving the session: cancelled from the admin, the hour goes back to the client.
  await page.getByRole("button", { name: `Annuler la séance de ${customerName(who)}` }).click();
  await page.getByRole("button", { name: "Confirmer l’annulation" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    `Séance de ${customerName(who)} annulée : l’heure lui a été recréditée et son lien lui a été renvoyé.`,
  );
  await expect(row.getByRole("cell").nth(3)).toHaveText("0 h");
  await expect(page.getByRole("button", { name: `Annuler la séance de ${customerName(who)}` })).toHaveCount(0);

  await page.getByRole("button", { name: "Déconnexion" }).click();
  await expect(page.getByRole("heading", { name: "Espace consultant" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Espace consultant" })).toBeVisible();
  expect((await request.get("/api/consultant/overview")).status()).toBe(401);
});

test("l'administrateur se connecte avec le mot de passe de secours, pas au cockpit", async ({ page }) => {
  await page.goto("/admin");
  const password = page.getByLabel("Mot de passe de secours");
  const submit = page.getByRole("button", { name: "Se connecter" });
  await expect(submit).toBeDisabled();
  await password.fill("mauvais");
  await submit.click();
  await expect(page.getByRole("alert")).toHaveText("Mot de passe incorrect.");
  await password.fill(ADMIN_PASSWORD);
  await submit.click();
  await expect(page.getByRole("heading", { name: "Comptes et rôles" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Relances et inactivité" })).toBeVisible();
  // Each area has its own session: the admin password does not open the cockpit.
  await page.goto("/consultant");
  await expect(page.getByRole("heading", { name: "Espace consultant" })).toBeVisible();
});
