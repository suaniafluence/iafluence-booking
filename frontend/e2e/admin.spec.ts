import { expect, test } from "@playwright/test";
import { ADMIN_PASSWORD } from "./env.mjs";
import { customerEmail, customerName, newCustomer } from "./helpers";

test("l'administrateur se connecte, suit les clients et se déconnecte", async ({ page, request }) => {
  // A customer who paid 2 h and booked the first session (through the public API).
  const who = newCustomer();
  const { token } = await (await request.get(`/api/checkout/cs_demo_2h_${who}`)).json();
  const { slots } = await (await request.get(`/api/availability?token=${token}`)).json();
  const booked = await request.post("/api/bookings", { data: { token, start: slots[0].start } });
  expect(booked.status()).toBe(201);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  const password = page.getByLabel("Mot de passe");
  const submit = page.getByRole("button", { name: "Se connecter" });
  await expect(submit).toBeDisabled();

  await password.fill("mauvais");
  await submit.click();
  await expect(page.getByRole("alert")).toHaveText("Mot de passe incorrect.");

  await password.fill(ADMIN_PASSWORD);
  await submit.click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();

  const row = page.getByRole("row").filter({ hasText: customerEmail(who) });
  await expect(row.getByRole("cell")).toHaveText([
    `${customerName(who)}${customerEmail(who)}`,
    "Conseil IA - 2h",
    "2 h",
    "1 h",
    "1 h",
    /^\p{Lu}\p{Ll}+ \d{1,2} \p{Ll}+ \d{4} · \d\d:\d\d$/u,
    "",
    "Copier le lien",
  ]);
  await expect(page.getByRole("listitem").filter({ hasText: customerName(who) })).toBeVisible();

  // Next-session link: drafted by default, sent automatically once ticked — the choice is saved.
  const autoSend = page.getByRole("checkbox", { name: `Envoi automatique pour ${customerName(who)}` });
  await expect(autoSend).not.toBeChecked();
  await autoSend.check();
  await expect(autoSend).toBeChecked();

  // A client who paid outside the website, added by hand.
  const manual = newCustomer();
  await page.getByRole("button", { name: "Ajouter un client" }).click();
  await page.getByLabel("Nom").fill(customerName(manual));
  await page.getByLabel("Email", { exact: true }).fill(customerEmail(manual));
  await page.getByLabel("Heures achetées").fill("3");
  await page.getByLabel("Montant payé (€)").fill("300");
  await page.getByRole("button", { name: "Ajouter le client" }).click();
  await expect(page.getByRole("alert")).toContainText("Client ajouté. Lien de réservation : http");
  const manualRow = page.getByRole("row").filter({ hasText: customerEmail(manual) });
  await expect(manualRow.getByRole("cell").nth(1)).toHaveText("Conseil IAmanuel");
  await expect(manualRow.getByRole("cell").nth(2)).toHaveText("3 h");

  // The session cookie survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(autoSend).toBeChecked();

  await page.getByRole("button", { name: "Déconnexion" }).click();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  expect((await request.get("/api/admin/overview")).status()).toBe(401);
});
