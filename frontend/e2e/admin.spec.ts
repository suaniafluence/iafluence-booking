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
  ]);
  await expect(page.getByRole("listitem").filter({ hasText: customerName(who) })).toBeVisible();

  // The session cookie survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();

  await page.getByRole("button", { name: "Déconnexion" }).click();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  expect((await request.get("/api/admin/overview")).status()).toBe(401);
});
