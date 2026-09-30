import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { ADMIN_PASSWORD, DATABASE_URL, OUTBOX_DIR } from "./env.mjs";

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

const backend = fileURLToPath(new URL("../../backend/", import.meta.url));

/** Runs Python in the backend environment, against the E2E database; returns its stdout. */
export function python(code: string): string {
  return execFileSync(process.env.UV ?? "uv", ["run", "python", "-c", code], {
    cwd: backend,
    env: { ...process.env, DATABASE_URL, PYTHONUTF8: "1" },
    stdio: ["ignore", "pipe", "inherit"],
  }).toString();
}

/** Moves the sessions of a customer into the past, as if they had just ended. */
export function endSessionsOf(email: string) {
  python(`
from sqlalchemy import text
from app.db import engine
with engine.begin() as c:
    c.execute(text("""UPDATE bookings SET start_datetime = now() - interval '62 minutes', end_datetime = now() - interval '2 minutes'
                      WHERE customer_id = (SELECT id FROM customers WHERE email = :e)"""), {"e": ${JSON.stringify(email)}})
`);
}

export type SavedEmail = { kind: "draft" | "sent"; to: string; subject: string; parts: string[]; text: string; html: string; cids: string[] };

/** Emails the demo mailer saved in the outbox (parsed by Python's email package). */
export function outbox(): SavedEmail[] {
  return JSON.parse(
    python(`
import email, json, pathlib
from email import policy
out = []
for f in sorted(pathlib.Path(${JSON.stringify(OUTBOX_DIR)}).glob("*.eml")):
    m = email.message_from_bytes(f.read_bytes(), policy=policy.default)
    body = m.get_body(("plain",))
    html = m.get_body(("html",))
    out.append({
        "kind": f.stem.rsplit("-", 1)[1], "to": m["To"], "subject": m["Subject"],
        "parts": [p.get_content_type() for p in m.walk()],
        "text": body.get_content() if body else "", "html": html.get_content() if html else "",
        "cids": [p["Content-ID"] for p in m.walk() if p["Content-ID"]],
    })
print(json.dumps(out))
`),
  );
}

export async function adminLogin(page: Page) {
  await page.goto("/admin");
  await page.getByLabel("Mot de passe").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

/** Books the first free slot for a new demo customer through the public API; returns the customer id. */
export async function bookedCustomer(request: APIRequestContext, hours = 2): Promise<string> {
  const who = newCustomer();
  const { token } = await (await request.get(`/api/checkout/cs_demo_${hours}h_${who}`)).json();
  const { slots } = await (await request.get(`/api/availability?token=${token}`)).json();
  const booked = await request.post("/api/bookings", { data: { token, start: slots[0].start } });
  expect(booked.status()).toBe(201);
  return who;
}
