import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Research } from "../../api";
import { company, learnerDetail, plan, planContent } from "../../test/fixtures";
import LearnerPage, { POLL_MS } from "./LearnerPage";

const plain = (s: string | null) => (s ?? "").replace(/\p{Zs}/gu, " ");

const show = () =>
  render(
    <MemoryRouter initialEntries={["/consultant/apprenants/7"]}>
      <Routes>
        <Route path="/consultant/apprenants/:id" element={<LearnerPage />} />
      </Routes>
    </MemoryRouter>,
  );

const section = (title: string) => screen.getByRole("heading", { name: title }).closest("section")!;

const RESEARCH: Research = {
  synthese: "Cabinet de conseil lyonnais de 4 personnes.",
  activite_reelle: ["Conseil en organisation pour PME"],
  personne: { role: "Gérant", linkedin_url: "https://www.linkedin.com/in/jean-dupont" },
  entreprise: { site_web: "https://dupont-conseil.fr", linkedin_url: "" },
  signaux_positifs: ["Recrute"],
  points_attention: [],
  angles_ia: ["Comptes rendus assistés"],
  questions_a_poser: ["Combien de missions ?"],
  sources: [{ titre: "Site officiel", url: "https://dupont-conseil.fr" }],
  confiance: "elevee",
};

beforeEach(() => {
  vi.spyOn(api, "learner").mockResolvedValue(learnerDetail());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LearnerPage", () => {
  it("shows the learner, their time, history and purchases", async () => {
    show();
    expect(screen.getByRole("status")).toHaveTextContent("Chargement…");
    expect(await screen.findByRole("heading", { name: "Jean Dupont" })).toBeInTheDocument();
    expect(api.learner).toHaveBeenCalledWith(7);
    expect(screen.getByText("jean@dupont-conseil.fr · Dupont Conseil")).toBeInTheDocument();
    const time = section("Temps");
    expect(within(time).getByRole("progressbar", { name: "Séances réalisées" })).toHaveAttribute("aria-valuenow", "40");
    expect(time).toHaveTextContent("2 faite(s) sur 5 · 3 restantes");
    expect(time).toHaveTextContent("2 séances de 60 min");
    expect(time).toHaveTextContent("Jeudi 8 octobre 2026 · 14:00");
    expect(time).toHaveTextContent("Une séance tous les 14 j · fin estimée lundi 16 novembre 2026");
    expect(time).not.toHaveTextContent("Inactivité");

    const history = section("Historique");
    expect(history).toHaveTextContent("Appel découverte");
    expect(history).toHaveTextContent("Sujet indiqué : Automatiser les devis");
    expect(within(history).getByText("Commencer par les devis")).toBeInTheDocument();

    const purchases = section("Achats");
    expect(plain(purchases.textContent)).toContain("Conseil IA - 5h · 2 h restantes sur 5 · 500,00 € · mardi 1 septembre 2026");
    expect(within(purchases).getByRole("button", { name: "Copier le lien" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Jamais montrées au client/)).toHaveValue("Très pressé");
  });

  it("a prospect without hours, idle, with an NDA and an erased report", async () => {
    const base = learnerDetail();
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        customer: { ...base.customer, company_name: null, nda_sent_at: "2026-09-01T10:00:00+02:00", notes: null },
        time: { ...base.time, status: "prospect", hours_purchased: 0, idle_days: 15, pace_days: null, next_session: null },
        purchases: [{ ...base.purchases[0], payment_status: "refunded", booking_url: null }],
        timeline: [{ ...base.timeline[0], kind: "session", label: "Conseil IA - 5h", status: "cancelled", message: null, report: { id: 2, status: "drafted", erased: true, synthese: null } }],
      }),
    );
    show();
    expect(await screen.findByText("jean@dupont-conseil.fr · NDA envoyé")).toBeInTheDocument();
    expect(section("Temps")).toHaveTextContent("Aucune heure achetée pour l’instant.");
    const history = section("Historique");
    expect(history).toHaveTextContent("Séance · Conseil IA - 5h (annulé)");
    expect(history).toHaveTextContent("Compte rendu effacé (durée de conservation).");
    expect(within(section("Achats")).getByRole("listitem")).toHaveClass("line-through");
    expect(within(section("Achats")).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Jamais montrées au client/)).toHaveValue("");
  });

  it("idle learner with an NDA signed, no history", async () => {
    const base = learnerDetail();
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        customer: { ...base.customer, nda_signed_at: "2026-09-02T10:00:00+02:00" },
        time: { ...base.time, idle_days: 1, next_session: null, pace_days: null },
        timeline: [],
        purchases: [],
      }),
    );
    show();
    expect(await screen.findByText("jean@dupont-conseil.fr · Dupont Conseil · NDA signé")).toBeInTheDocument();
    expect(section("Temps")).toHaveTextContent("Pas encore réservée");
    expect(section("Temps")).toHaveTextContent("1 jour sans séance");
    expect(screen.getByText("Aucun rendez-vous.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Achats" })).not.toBeInTheDocument();
  });

  it("asks to sign in", async () => {
    vi.mocked(api.learner).mockRejectedValue(new ApiError(401, "Authentification requise."));
    vi.spyOn(api, "authMethods").mockResolvedValue({ google: true, password: false });
    show();
    expect(await screen.findByRole("link", { name: "Se connecter avec Google" })).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.learner).mockRejectedValue(new ApiError(404, "Apprenant introuvable."));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Apprenant introuvable.");
    expect(screen.getByRole("link", { name: "← Cockpit" })).toHaveAttribute("href", "/consultant");
  });

  it("changes how the learner came", async () => {
    vi.spyOn(api, "updateLearner").mockResolvedValue({
      customer_id: 7,
      company_name: null,
      notes: null,
      acquisition_source: "autre",
      acquisition_detail: "Salon",
    });
    const user = userEvent.setup();
    show();
    const select = await screen.findByLabelText("Comment ce client est arrivé");
    expect(select).toHaveValue("whatsapp");
    await user.selectOptions(select, "Autre");
    await user.type(screen.getByLabelText("Précisez"), "Salon");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(api.updateLearner).toHaveBeenCalledWith(7, { acquisition_source: "autre", acquisition_detail: "Salon" });
    expect(await screen.findByText("Enregistré.")).toBeInTheDocument();
  });

  it("saves the notes, or says why not", async () => {
    vi.spyOn(api, "updateLearner")
      .mockResolvedValueOnce({ customer_id: 7, company_name: null, notes: "x", acquisition_source: null, acquisition_detail: null })
      .mockRejectedValueOnce(new ApiError(422, "Trop long."));
    const user = userEvent.setup();
    show();
    const notes = await screen.findByLabelText(/Jamais montrées au client/);
    await user.clear(notes);
    await user.type(notes, "Budget serré");
    await user.click(screen.getByRole("button", { name: "Enregistrer les notes" }));
    expect(api.updateLearner).toHaveBeenCalledWith(7, { notes: "Budget serré" });
    expect(await screen.findByText("Enregistré.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Enregistrer les notes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Trop long.");
    expect(screen.queryByText("Enregistré.")).not.toBeInTheDocument();
  });

  it("polls while Codex works, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.learner)
      .mockResolvedValueOnce(learnerDetail({ plan: plan({ status: "generating", busy: true, content: null, messages: [] }) }))
      .mockResolvedValue(learnerDetail({ plan: plan() }));
    show();
    expect(await screen.findByText("Rédaction en cours par Codex (quelques minutes)…")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await screen.findByText("Diviser par trois le temps des devis")).toBeInTheDocument();
    expect(api.learner).toHaveBeenCalledTimes(2);
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 2));
    expect(api.learner).toHaveBeenCalledTimes(2);
  });

  it("polls while the research runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.learner)
      .mockResolvedValueOnce(learnerDetail({ research: { status: "running", content: null, error: null, updated_at: null } }))
      .mockResolvedValue(learnerDetail({ research: { status: "ready", content: RESEARCH, error: null, updated_at: null } }));
    show();
    expect(await screen.findByText("Recherche en cours (quelques minutes)…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lancer la recherche" })).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await screen.findByText("Cabinet de conseil lyonnais de 4 personnes.")).toBeInTheDocument();
  });
});

describe("Plan panel", () => {
  it("generates the first plan", async () => {
    vi.spyOn(api, "generatePlan").mockResolvedValue({ status: "pending" });
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Générer le plan" }));
    expect(api.generatePlan).toHaveBeenCalledWith(7);
    expect(api.learner).toHaveBeenCalledTimes(2);
  });

  it("shows why the plan could not be queued", async () => {
    vi.spyOn(api, "generatePlan").mockRejectedValue(new ApiError(409, "Codex n'est pas configuré sur ce serveur."));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Générer le plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Codex n'est pas configuré");
  });

  it("renders the plan with its timed sessions", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        plan: plan({
          content: planContent({ hypotheses_a_verifier: ["Volume réel"], seances: [{ ...planContent().seances[0], preparation_client: [] }] }),
        }),
      }),
    );
    show();
    const panel = await screen.findByText("Diviser par trois le temps des devis").then((el) => el.closest("section")!);
    expect(panel).toHaveTextContent("Version 1 · à relire");
    expect(panel).toHaveTextContent("Devis — Cité en premier · gain : 4 h/semaine · effort faible");
    expect(panel).toHaveTextContent("Séance 1 — Cadrage60 min");
    expect(panel).toHaveTextContent("10 minPoint50 minAtelier");
    expect(panel).toHaveTextContent("Livrable : Prototype");
    expect(panel).not.toHaveTextContent("À préparer par le client");
    expect(panel).toHaveTextContent("RGPD → Compte pro");
    expect(panel).toHaveTextContent("ChatGPT Team : Rédaction (30 €/mois)");
    expect(panel).toHaveTextContent("Volume réel");
    expect(panel).toHaveTextContent("Qui valide ?");
    expect(within(panel).getByRole("list", { name: "Conversation" })).toHaveTextContent("Codex : Choix : les devis d'abord.");
  });

  it("validates, regenerates and chats", async () => {
    vi.spyOn(api, "validatePlan").mockResolvedValue({ validated_at: "2026-10-05T08:00:00+02:00" });
    vi.spyOn(api, "generatePlan").mockResolvedValue({ status: "pending" });
    vi.spyOn(api, "sendPlanMessage").mockResolvedValue({ status: "pending" });
    vi.mocked(api.learner).mockResolvedValue(learnerDetail({ plan: plan() }));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Valider le plan" }));
    expect(api.validatePlan).toHaveBeenCalledWith(7, true);
    await user.click(screen.getByRole("button", { name: "Régénérer" }));
    expect(api.generatePlan).toHaveBeenCalledWith(7);

    const send = screen.getByRole("button", { name: "Envoyer" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("Votre demande"), "Pas de budget logiciel");
    await user.click(send);
    expect(api.sendPlanMessage).toHaveBeenCalledWith(7, "Pas de budget logiciel");
    expect(screen.getByLabelText("Votre demande")).toHaveValue("");
  });

  it("keeps the message when it could not be sent", async () => {
    vi.spyOn(api, "sendPlanMessage").mockRejectedValue(new ApiError(409, "Le plan est en cours de rédaction : attendez la réponse."));
    vi.mocked(api.learner).mockResolvedValue(learnerDetail({ plan: plan() }));
    const user = userEvent.setup();
    show();
    await user.type(await screen.findByLabelText("Votre demande"), "Et alors ?");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("en cours de rédaction");
    expect(screen.getByLabelText("Votre demande")).toHaveValue("Et alors ?");
  });

  it("a validated plan, the consultant's messages, and a busy chat", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        plan: plan({
          validated_at: "2026-10-05T08:00:00+02:00",
          busy: true,
          status: "pending",
          messages: [{ role: "consultant", content: "Plus court", created_at: null }],
        }),
      }),
    );
    show();
    expect(await screen.findByText(/Version 1 · validée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer la validation" })).toBeDisabled();
    expect(screen.getByRole("list", { name: "Conversation" })).toHaveTextContent("Vous : Plus court");
    expect(screen.getByRole("button", { name: "Envoyer" })).toBeDisabled();
  });

  it("a failed first draft can be written again", async () => {
    vi.spyOn(api, "generatePlan").mockResolvedValue({ status: "pending" });
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({ plan: plan({ status: "failed", content: null, error: "Plan impossible à rédiger : sortie Codex invalide", messages: [] }) }),
    );
    const user = userEvent.setup();
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Plan impossible à rédiger");
    await user.click(screen.getByRole("button", { name: "Relancer la rédaction" }));
    expect(api.generatePlan).toHaveBeenCalledWith(7);
    expect(screen.queryByLabelText("Votre demande")).not.toBeInTheDocument();
  });
});

describe("Company panel", () => {
  it("searches from the suggestion, then associates a company", async () => {
    vi.spyOn(api, "companySearch")
      .mockResolvedValueOnce({ query: "dupont conseil", results: [company(), company({ siren: "999999999", nom: "DUPONT BIS", adresse: null, etat: "cessee" })] })
      .mockResolvedValueOnce({ query: "zzz", results: [] });
    vi.spyOn(api, "companyAttach").mockResolvedValue(company());
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Rechercher l’entreprise" }));
    expect(api.companySearch).toHaveBeenCalledWith(7, undefined);
    const results = await screen.findByRole("list", { name: "Résultats" });
    expect(screen.getByLabelText("Nom ou SIREN")).toHaveValue("dupont conseil");
    const items = within(results).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("DUPONT CONSEIL 812345678 · 1 rue X 69001 LYON");
    expect(items[1]).toHaveTextContent("DUPONT BIS 999999999 · fermée");

    await user.clear(screen.getByLabelText("Nom ou SIREN"));
    await user.type(screen.getByLabelText("Nom ou SIREN"), "zzz");
    await user.click(screen.getByRole("button", { name: "Rechercher" }));
    expect(api.companySearch).toHaveBeenLastCalledWith(7, "zzz");
    expect(await screen.findByText("Aucun résultat.")).toBeInTheDocument();

    vi.mocked(api.companySearch).mockResolvedValueOnce({ query: "dupont", results: [company()] });
    await user.click(screen.getByRole("button", { name: "Rechercher" }));
    await user.click(await screen.findByRole("button", { name: "Associer" }));
    expect(api.companyAttach).toHaveBeenCalledWith(7, "812345678");
    expect(api.learner).toHaveBeenCalledTimes(2);
  });

  it("cancels the search, and shows search and association errors", async () => {
    vi.spyOn(api, "companySearch")
      .mockRejectedValueOnce(new ApiError(502, "Annuaire des entreprises injoignable."))
      .mockResolvedValue({ query: "d", results: [company()] });
    vi.spyOn(api, "companyAttach").mockRejectedValue(new ApiError(404, "Aucune entreprise avec ce SIREN."));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Rechercher l’entreprise" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("injoignable");
    expect(screen.getByRole("button", { name: "Rechercher" })).toBeDisabled();
    await user.type(screen.getByLabelText("Nom ou SIREN"), "du");
    await user.click(screen.getByRole("button", { name: "Rechercher" }));
    await user.click(await screen.findByRole("button", { name: "Associer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Aucune entreprise avec ce SIREN.");
    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.getByText("Aucune entreprise associée.")).toBeInTheDocument();
  });

  it("shows the company card, then changes or removes it", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({ company: company({ etat: "cessee", finances: [{ annee: 2024, ca: 300000, resultat_net: -5000 }, { annee: 2023, ca: null, resultat_net: 2000 }] }) }),
    );
    vi.spyOn(api, "companyDetach").mockResolvedValueOnce({ status: "detached" }).mockRejectedValueOnce(new ApiError(500, "Oups."));
    vi.spyOn(api, "companySearch").mockResolvedValue({ query: "x", results: [] });
    const user = userEvent.setup();
    show();
    const card = await screen.findByRole("heading", { name: "Entreprise" }).then((h) => h.closest("section")!);
    expect(card).toHaveTextContent("DUPONT CONSEIL (fermée)");
    expect(card).toHaveTextContent("SIREN 812345678 · NAF 70.22Z · créée le 2015-06-01");
    expect(card).toHaveTextContent("Effectif : 3 à 5 salariés (2023)");
    expect(card).toHaveTextContent("Catégorie : PME");
    expect(card).toHaveTextContent("Labels : Certifié Qualiopi");
    expect(card).toHaveTextContent("Dirigeants : Jean DUPONT (Gérant)");
    expect(within(card).getByText("Résultat net négatif en 2024")).toHaveAttribute("data-level", "attention");
    const rows = within(card).getAllByRole("row");
    expect(plain(rows[1].textContent)).toBe("2024300 000 €-5 000 €");
    expect(within(rows[1]).getAllByRole("cell")[2]).toHaveClass("text-red-700");
    expect(plain(rows[2].textContent)).toBe("2023—2 000 €");

    await user.click(within(card).getByRole("button", { name: "Retirer" }));
    expect(api.companyDetach).toHaveBeenCalledWith(7);
    await user.click(within(card).getByRole("button", { name: "Retirer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Oups.");
    await user.click(within(card).getByRole("button", { name: "Changer d’entreprise" }));
    expect(await screen.findByText("Aucun résultat.")).toBeInTheDocument();
  });

  it("a sparse company card", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        company: company({ activite_code: null, date_creation: null, adresse: null, effectif: null, categorie: null, labels: [], dirigeants: [{ nom: "HOLDING X", qualite: "" }], finances: [], signaux: [] }),
      }),
    );
    show();
    const card = await screen.findByRole("heading", { name: "Entreprise" }).then((h) => h.closest("section")!);
    expect(card).toHaveTextContent("SIREN 812345678Dirigeants : HOLDING X");
    expect(within(card).queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("Research panel", () => {
  it("starts a research", async () => {
    vi.spyOn(api, "startResearch").mockResolvedValue({ status: "running" });
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Lancer la recherche" }));
    expect(api.startResearch).toHaveBeenCalledWith(7);
    expect(api.learner).toHaveBeenCalledTimes(2);
  });

  it("shows the note with safe external links", async () => {
    vi.mocked(api.learner).mockResolvedValue(learnerDetail({ research: { status: "ready", content: RESEARCH, error: null, updated_at: null } }));
    show();
    const panel = await screen.findByRole("heading", { name: "Recherche web" }).then((h) => h.closest("section")!);
    expect(panel).toHaveTextContent("Confiance : élevée");
    expect(panel).toHaveTextContent("Rôle : Gérant");
    const linkedin = within(panel).getByRole("link", { name: "LinkedIn de la personne" });
    expect(linkedin).toHaveAttribute("href", "https://www.linkedin.com/in/jean-dupont");
    expect(linkedin).toHaveAttribute("target", "_blank");
    expect(linkedin).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(panel).getByRole("link", { name: "Site web" })).toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "LinkedIn de l’entreprise" })).not.toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Site officiel" })).toHaveAttribute("href", "https://dupont-conseil.fr");
    expect(panel).toHaveTextContent("Comptes rendus assistés");
    expect(panel).not.toHaveTextContent("Points d’attention");
    expect(within(panel).getByRole("button", { name: "Relancer la recherche" })).toBeEnabled();
  });

  it("a sparse note", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({
        research: {
          status: "ready",
          content: { ...RESEARCH, personne: { role: "", linkedin_url: "" }, entreprise: { site_web: "", linkedin_url: "https://linkedin.com/company/x" }, sources: [], confiance: "faible" },
          error: null,
          updated_at: null,
        },
      }),
    );
    show();
    const panel = await screen.findByRole("heading", { name: "Recherche web" }).then((h) => h.closest("section")!);
    expect(panel).toHaveTextContent("Confiance : faible");
    expect(panel).not.toHaveTextContent("Rôle :");
    expect(panel).not.toHaveTextContent("Sources");
    expect(within(panel).getByRole("link", { name: "LinkedIn de l’entreprise" })).toBeInTheDocument();
  });

  it("shows a failed research and a refused start", async () => {
    vi.mocked(api.learner).mockResolvedValue(
      learnerDetail({ research: { status: "failed", content: null, error: "Recherche impossible : délai dépassé", updated_at: null } }),
    );
    vi.spyOn(api, "startResearch").mockRejectedValue(new ApiError(409, "Une recherche est déjà en cours pour ce client."));
    const user = userEvent.setup();
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("délai dépassé");
    await user.click(screen.getByRole("button", { name: "Lancer la recherche" }));
    expect(await screen.findByText("Une recherche est déjà en cours pour ce client.")).toBeInTheDocument();
  });
});
