import { expect, test } from "@playwright/test";
import { adminLogin } from "./helpers";

// Demo mode: the codex app-server is faked and the admin « approves » on the OpenAI page after 4 s.
test("l'administrateur connecte Codex avec un code appareil, puis le déconnecte", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await adminLogin(page);

  const codex = page.locator("section").filter({ has: page.getByRole("heading", { name: "Connexion Codex" }) });
  await expect(codex.getByText("Non connecté")).toBeVisible();
  await codex.getByRole("button", { name: "Connecter Codex" }).click();

  // Step 1: the OpenAI verification page, to copy or open.
  await expect(codex.getByText("https://auth.openai.com/codex/device", { exact: true })).toBeVisible();
  const open = codex.getByRole("link", { name: "Ouvrir OpenAI" });
  await expect(open).toHaveAttribute("href", "https://auth.openai.com/codex/device");
  await expect(open).toHaveAttribute("target", "_blank");
  await codex.getByRole("button", { name: "Copier l’adresse de connexion" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("https://auth.openai.com/codex/device");

  // Step 2: the one-time code, never a password or a token.
  const code = codex.getByLabel("Code de connexion");
  await expect(code).toHaveText(/^[A-Z]{4}-\d{4}$/);
  await codex.getByRole("button", { name: "Copier le code" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(await code.textContent());
  await expect(codex.getByRole("status")).toContainText("En attente de la validation…");

  // The page checks every 3 s and switches to « Connecté » by itself.
  await expect(codex.getByRole("alert")).toHaveText(
    "Codex est connecté : les résumés utiliseront votre forfait ChatGPT.",
    { timeout: 15_000 },
  );
  await expect(codex.getByText("Connecté", { exact: true })).toBeVisible();
  await expect(codex.getByText(/Compte ChatGPT/)).toHaveText("Compte ChatGPT : demo@iafluence.fr · forfait plus");
  await expect(code).toHaveCount(0);

  // Still connected after a reload.
  await page.reload();
  await expect(codex.getByText("Connecté", { exact: true })).toBeVisible();

  await codex.getByRole("button", { name: "Déconnecter" }).click();
  await expect(codex.getByRole("alert")).toHaveText("Codex est déconnecté.");
  await expect(codex.getByText("Non connecté")).toBeVisible();
});

test("une connexion Codex en attente peut être annulée", async ({ page }) => {
  await adminLogin(page);
  const codex = page.locator("section").filter({ has: page.getByRole("heading", { name: "Connexion Codex" }) });
  await codex.getByRole("button", { name: "Connecter Codex" }).click();
  await expect(codex.getByLabel("Code de connexion")).toBeVisible();
  await codex.getByRole("button", { name: "Annuler la connexion" }).click();
  await expect(codex.getByRole("alert")).toHaveText("Connexion annulée.");
  await expect(codex.getByRole("button", { name: "Connecter Codex" })).toBeVisible();
  // The cancelled login never completes, even after the demo delay.
  await page.waitForTimeout(5_000);
  await page.reload();
  await expect(codex.getByText("Non connecté")).toBeVisible();
});
