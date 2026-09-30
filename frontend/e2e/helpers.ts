import { expect, type Page } from "@playwright/test";

let seq = 0;

/** Unique demo customer id: the demo Stripe accepts any `cs_demo_<hours>h_<[a-z0-9]+>` session. */
export function newCustomer(): string {
  return `e2e${Date.now().toString(36)}${(seq++).toString(36)}`;
}

/** Demo Stripe derives the customer from the session id. */
export const customerEmail = (who: string) => `${who}@example.com`;
export const customerName = (who: string) => `${who.charAt(0).toUpperCase()}${who.slice(1)} Démo`;

/** Simulates the redirect Stripe performs after a successful payment. */
export async function arriveFromStripe(page: Page, hours = 5, who = newCustomer()): Promise<string> {
  await page.goto(`/reservation?session_id=cs_demo_${hours}h_${who}`);
  // 256-bit url-safe token, and the Stripe session id is gone from the address bar.
  await expect(page).toHaveURL(/\/reservation\/[A-Za-z0-9_-]{43}$/);
  return who;
}

export async function openSlotPicker(page: Page) {
  await page.getByRole("button", { name: "Choisir mon créneau" }).click();
  await expect(page.getByRole("heading", { name: "Choisissez votre créneau" })).toBeVisible();
  await expect(page.getByRole("tablist", { name: "Jours disponibles" })).toBeVisible();
}

export const timeButtons = (page: Page) => page.getByRole("button", { name: /^\d\d:\d\d$/ });

/** Value of a row in an hours summary (<dl>). */
export const summaryValue = (page: Page, label: string) =>
  page
    .locator("dl > div")
    .filter({ has: page.getByRole("term").filter({ hasText: new RegExp(`^${label}$`) }) })
    .getByRole("definition");
