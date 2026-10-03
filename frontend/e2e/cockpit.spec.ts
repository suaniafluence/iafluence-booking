import { expect, test } from "@playwright/test";
import { bookedCustomer, connectCodex, consultantLogin, customerName } from "./helpers";

// Demo mode: the demo agent writes a plan that fits the sessions left; the register returns a fictitious company.
test("fiche apprenant : temps, entreprise, recherche web et plan d'action discuté par chat", async ({ page, request }) => {
  const who = await bookedCustomer(request, 3);
  await connectCodex(page);
  await consultantLogin(page);

  await page.getByRole("link").filter({ hasText: customerName(who) }).click();
  await expect(page.getByRole("heading", { name: customerName(who) })).toBeVisible();
  const time = page.locator("section").filter({ has: page.getByRole("heading", { name: "Temps" }) });
  await expect(time).toContainText("0 faite(s) sur 3 · 3 restantes");

  // Company from the official register.
  const companyPanel = page.locator("section").filter({ has: page.getByRole("heading", { name: "Entreprise" }) });
  await companyPanel.getByRole("button", { name: "Rechercher l’entreprise" }).click();
  // example.com is a webmail-like domain: nothing to suggest.
  await expect(companyPanel.getByText("Aucun résultat.")).toBeVisible();
  await companyPanel.getByLabel("Nom ou SIREN").fill("acme");
  await companyPanel.getByRole("button", { name: "Rechercher" }).click();
  await companyPanel.getByRole("button", { name: "Associer" }).click();
  await expect(companyPanel).toContainText("SIREN 123456789");

  // Web research.
  const research = page.locator("section").filter({ has: page.getByRole("heading", { name: "Recherche web" }) });
  await research.getByRole("button", { name: "Lancer la recherche" }).click();
  await expect(research).toContainText("Confiance : faible", { timeout: 15_000 });

  // Action plan, then a chat message.
  const plan = page.locator("section").filter({ has: page.getByRole("heading", { name: "Plan d’action" }) });
  await plan.getByRole("button", { name: "Générer le plan" }).click();
  await expect(plan).toContainText("Version 1 · à relire", { timeout: 15_000 });
  await expect(plan).toContainText("Séance 3 — Autonomie et feuille de route");
  await page.getByLabel("Votre demande").fill("Ajoute un atelier sur les avis Google");
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(plan).toContainText("Version 2", { timeout: 15_000 });
  await expect(page.getByRole("list", { name: "Conversation" })).toContainText("Ajoute un atelier sur les avis Google");
  await plan.getByRole("button", { name: "Valider le plan" }).click();
  await expect(plan).toContainText("Version 2 · validée");

  // Leave Codex disconnected, as the other specs expect.
  await page.goto("/admin");
  const codex = page.locator("section").filter({ has: page.getByRole("heading", { name: "Connexion Codex" }) });
  await codex.getByRole("button", { name: "Déconnecter" }).click();
  await expect(codex.getByText("Non connecté")).toBeVisible();
});
