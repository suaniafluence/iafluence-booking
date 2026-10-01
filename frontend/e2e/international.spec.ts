import { expect, test } from "@playwright/test";
import { customerEmail, newCustomer, summaryValue } from "./helpers";

// A customer who paid on the English page of iafluence.fr (payment link opened with ?locale=en),
// booking from Sydney: 9 to 10 hours ahead of Paris, often already the next day.
test.describe("client à l'étranger", () => {
  test.use({ locale: "en-AU", timezoneId: "Australia/Sydney" });

  test("Sydney, lien de paiement anglais @mobile", async ({ page }) => {
    const who = newCustomer();
    await page.goto(`/reservation?session_id=cs_demo_3h_${who}_en`);
    await expect(page).toHaveURL(/\/en\/reservation\/[A-Za-z0-9_-]{43}$/);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Your AI consulting is confirmed" })).toBeVisible();
    await expect(summaryValue(page, "Hours purchased")).toHaveText("3 h");

    await page.getByRole("button", { name: "Choose a time" }).click();
    await expect(page.getByText("One-hour session · times shown in Sydney time, with Paris time below")).toBeVisible();
    // Every slot shows Sydney time, with Paris time (and weekday when Paris is still on the previous day).
    const slots = page.getByRole("button", { name: /^\d\d:\d\d \(Paris (\w{3} )?\d\d:\d\d\)$/ });
    await expect(slots.first()).toBeVisible();
    const label = (await slots.first().getAttribute("aria-label"))!;
    const [, sydney, paris] = label.match(/^(\d\d:\d\d) \(Paris (?:\w{3} )?(\d\d:\d\d)\)$/)!;
    await slots.first().click();

    await expect(page.getByRole("heading", { name: "Your appointment" })).toBeVisible();
    await expect(page.getByText("Sydney time")).toBeVisible();
    await expect(page.getByText(new RegExp(`^${sydney} - `))).toBeVisible();
    await expect(page.getByText(new RegExp(`^Paris time: .*, ${paris} - `))).toBeVisible();
    await expect(page.getByText(customerEmail(who))).toBeVisible();
    await page.getByRole("button", { name: "Confirm appointment" }).click();

    await expect(page.getByRole("heading", { name: "Appointment confirmed" })).toBeVisible();
    await expect(page.getByText(new RegExp(`^${sydney} - .* · AI consulting with Suan Tay$`))).toBeVisible();
    await expect(summaryValue(page, "Hours left")).toHaveText("2 h");

    // Same page in Spanish: the booking is kept.
    await page.getByRole("link", { name: "Español" }).click();
    await expect(page).toHaveURL(/\/es\/reservation\//);
    await expect(page.getByRole("heading", { name: "Cita confirmada" })).toBeVisible();
    await expect(page.getByText(/^Hora de París: /)).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Cita confirmada" })).toBeVisible();
  });
});
