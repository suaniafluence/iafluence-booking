import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { codexStatus, deferred, firefliesStatus, overview } from "../test/fixtures";
import { MemoryRouter } from "react-router-dom";
import Cockpit from "./Cockpit";

const plain = (s: string | null) => (s ?? "").replace(/\p{Zs}/gu, " ");
const unauthorized = () => new ApiError(401, "Authentification requise.");
/** Opened on one tab, as from a link to /consultant#clients. */
const renderCockpit = (tab = "") => {
  window.history.replaceState(null, "", tab ? `#${tab}` : window.location.pathname);
  return render(
    <MemoryRouter>
      <Cockpit />
    </MemoryRouter>,
  );
};

beforeEach(() => {
  vi.spyOn(api, "adminOverview").mockResolvedValue(overview());
  vi.spyOn(api, "adminCodexStatus").mockResolvedValue(codexStatus({ state: "connected", email: "suan@iafluence.fr" }));
  vi.spyOn(api, "adminFirefliesStatus").mockResolvedValue(firefliesStatus());
  vi.spyOn(api, "adminNda").mockResolvedValue({ documents: [], customers: [] });
  vi.spyOn(api, "learners").mockResolvedValue({
    learners: [],
    hidden_count: 0,
    settings: { reminder_after_days: 21, hide_after_days: 60, session_duration_min: 60 },
  });
});

describe("Cockpit", () => {
  it("shows a spinner then the dashboard KPIs", async () => {
    const data = deferred<ReturnType<typeof overview>>();
    vi.mocked(api.adminOverview).mockReturnValue(data.promise);
    renderCockpit();
    expect(screen.getByRole("status")).toHaveTextContent("Chargement…");
    data.resolve(overview());

    await screen.findByRole("tab", { name: "Prochains rendez-vous" });
    const kpi = (label: string) => screen.getByText(label).parentElement!;
    expect(plain(kpi("Paiements du mois").textContent)).toBe("Paiements du mois31 500,00 €");
    expect(kpi("Heures vendues")).toHaveTextContent("8 h");
    expect(kpi("Heures vendues").children).toHaveLength(2); // no empty hint line
    expect(kpi("Heures réalisées")).toHaveTextContent("1,5 h");
    expect(kpi("Heures restantes à délivrer")).toHaveTextContent("6,5 h");
    expect(kpi("Heures à planifier")).toHaveTextContent("6 h2 h réservées");
    expect(await screen.findByText("Aucun apprenant actif.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("lists upcoming meetings with an optional Meet link", async () => {
    renderCockpit("rendez-vous");
    const list = (await screen.findByRole("heading", { name: "Prochains rendez-vous" })).nextElementSibling as HTMLElement;
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Jean Dupontjean@example.comJeudi 8 octobre 202614:00 - 15:00 · Meet");
    expect(within(items[0]).getByRole("link", { name: "Meet" })).toHaveAttribute("href", "https://meet.google.com/abc");
    expect(within(items[0]).getByRole("link")).toHaveAttribute("target", "_blank");
    expect(items[1]).toHaveTextContent("Marie Martin");
    expect(within(items[1]).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("Aucun rendez-vous à venir.")).not.toBeInTheDocument();
  });

  it("lists clients, striking refunded purchases", async () => {
    renderCockpit("clients");
    const rows = within((await screen.findAllByRole("table"))[0]).getAllByRole("row");
    expect(rows[0]).toHaveTextContent("ClientPrestationAchetéesRéservéesRestantesProchaine sessionEnvoi autoLien");
    const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells(rows[1])).toEqual([
      "Jean Dupontjean@example.com",
      "Conseil IA - 5h",
      "5 hModifier",
      "1 h",
      "4 h",
      "Jeudi 8 octobre 2026 · 14:00",
      "",
      "Copier le lien",
    ]);
    expect(cells(rows[2])[1]).toBe("Conseil IA - 1hmanuel");
    expect(cells(rows[2])[7]).toBe("—");
    expect(screen.getByRole("checkbox", { name: "Envoi automatique pour Jean Dupont" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Envoi automatique pour Paul Rembourse" })).not.toBeChecked();
    expect(rows[1]).not.toHaveClass("line-through");
    expect(cells(rows[2])[5]).toBe("—");
    expect(rows[2]).toHaveClass("line-through");
    expect(rows).toHaveLength(3);
    expect(screen.queryByText("Aucun client pour le moment.")).not.toBeInTheDocument();
  });

  it("handles empty lists", async () => {
    vi.mocked(api.adminOverview).mockResolvedValue(overview({ upcoming: [], clients: [] }));
    renderCockpit();
    expect(await screen.findByText("Aucun rendez-vous à venir.")).toBeInTheDocument();
    expect(screen.getByText("Aucun client pour le moment.")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.adminOverview).mockRejectedValue(new ApiError(500, "Une erreur est survenue."));
    renderCockpit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Une erreur est survenue.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Espace consultant" })).not.toBeInTheDocument();
  });

  it("asks unauthenticated visitors to sign in with Google", async () => {
    vi.mocked(api.adminOverview).mockRejectedValueOnce(unauthorized());
    vi.spyOn(api, "authMethods").mockResolvedValue({ google: true, password: true });
    renderCockpit();
    expect(await screen.findByRole("heading", { name: "Espace consultant" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Se connecter avec Google" })).toHaveAttribute(
      "href",
      "/api/auth/google/start?role=consultant",
    );
    // The password fallback is the admin's only.
    expect(screen.queryByLabelText("Mot de passe de secours")).not.toBeInTheDocument();
  });

  it("a removed role also leads to the sign-in page", async () => {
    vi.mocked(api.adminOverview).mockRejectedValueOnce(new ApiError(403, "Accès retiré."));
    vi.spyOn(api, "authMethods").mockResolvedValue({ google: true, password: false });
    renderCockpit();
    expect(await screen.findByRole("heading", { name: "Espace consultant" })).toBeInTheDocument();
  });

  it("logs out back to the sign-in page, even if the request fails", async () => {
    vi.spyOn(api, "authLogout").mockRejectedValue(new ApiError(0, "offline"));
    vi.spyOn(api, "authMethods").mockResolvedValue({ google: true, password: false });
    const user = userEvent.setup();
    renderCockpit();
    await user.click(await screen.findByRole("button", { name: "Déconnexion" }));
    expect(api.authLogout).toHaveBeenCalledWith("consultant");
    expect(await screen.findByRole("heading", { name: "Espace consultant" })).toBeInTheDocument();
  });

  it("toggles automatic sending per client and reloads", async () => {
    const saved = deferred<{ customer_id: number; auto_send_next_link: boolean }>();
    vi.spyOn(api, "adminSetAutoSend").mockReturnValue(saved.promise);
    const user = userEvent.setup();
    renderCockpit("clients");
    const box = await screen.findByRole("checkbox", { name: "Envoi automatique pour Paul Rembourse" });
    expect(screen.getByText(/sinon il est préparé en brouillon dans Gmail/)).toBeInTheDocument();

    await user.click(box);
    expect(api.adminSetAutoSend).toHaveBeenCalledWith(11, true);
    expect(box).toBeDisabled();
    expect(box).toBeChecked(); // shown at once
    expect(screen.getByRole("checkbox", { name: "Envoi automatique pour Jean Dupont" })).toBeEnabled();

    saved.resolve({ customer_id: 11, auto_send_next_link: true });
    await vi.waitFor(() => expect(api.adminOverview).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(screen.getByRole("checkbox", { name: "Envoi automatique pour Paul Rembourse" })).toBeEnabled());

    vi.mocked(api.adminSetAutoSend).mockResolvedValue({ customer_id: 10, auto_send_next_link: false });
    await user.click(screen.getByRole("checkbox", { name: "Envoi automatique pour Jean Dupont" }));
    expect(api.adminSetAutoSend).toHaveBeenLastCalledWith(10, false);
  });

  it("shows an error when the auto-send choice cannot be saved", async () => {
    vi.spyOn(api, "adminSetAutoSend").mockRejectedValue(new ApiError(500, "Enregistrement impossible."));
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("checkbox", { name: "Envoi automatique pour Paul Rembourse" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enregistrement impossible.");
    expect(api.adminOverview).toHaveBeenCalledTimes(1);
    const box = screen.getByRole("checkbox", { name: "Envoi automatique pour Paul Rembourse" });
    expect(box).toBeEnabled();
    expect(box).not.toBeChecked(); // back to the saved value
    expect(screen.getByRole("checkbox", { name: "Envoi automatique pour Jean Dupont" })).toBeChecked();
  });

  it("copies a client's booking link", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Copier le lien" }));
    expect(writeText).toHaveBeenCalledWith("https://booking.test/reservation/tokJ");
    expect(await screen.findByRole("button", { name: "Copié" })).toBeInTheDocument();
  });

  it("keeps the copy button as is when the clipboard is unavailable", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Copier le lien" }));
    expect(writeText).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Copier le lien" })).toBeInTheDocument();
  });

  it("adds a client by hand and shows the booking link", async () => {
    const added = deferred<{ customer_id: number; purchase_id: number | null; booking_url: string | null }>();
    vi.spyOn(api, "adminAddClient").mockReturnValue(added.promise);
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Ajouter un client" }));
    expect(screen.queryByRole("button", { name: "Ajouter un client" })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Heures achetées/)).toHaveValue(null);
    expect(screen.getByLabelText("Prestation")).toBeDisabled();
    expect(screen.getByLabelText("Envoyer le lien de réservation par email")).toBeDisabled();

    await user.type(screen.getByLabelText("Nom"), "Claire Durand");
    await user.type(screen.getByLabelText("Email"), "claire@example.com");
    await user.selectOptions(screen.getByLabelText("Mode d’acquisition"), "LinkedIn");
    await user.type(screen.getByLabelText(/Heures achetées/), "4");
    expect(screen.getByLabelText("Envoyer le lien de réservation par email")).toBeChecked();
    await user.type(screen.getByLabelText("Montant payé (€)"), "480,50");
    await user.clear(screen.getByLabelText("Prestation"));
    await user.type(screen.getByLabelText("Prestation"), "Atelier IA");
    await user.click(screen.getByLabelText("Envoyer le lien de réservation par email"));
    await user.click(screen.getByRole("button", { name: "Ajouter le client" }));

    expect(api.adminAddClient).toHaveBeenCalledWith({
      name: "Claire Durand",
      email: "claire@example.com",
      acquisition_source: "linkedin",
      acquisition_detail: undefined,
      hours: 4,
      product_name: "Atelier IA",
      amount_cents: 48_050,
      send_link: false,
    });
    expect(screen.getByRole("button", { name: "Ajout…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Annuler" })).toBeDisabled();

    added.resolve({ customer_id: 9, purchase_id: 3, booking_url: "https://booking.test/reservation/tokC" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Client ajouté. Lien de réservation : https://booking.test/reservation/tokC");
    expect(within(alert).getByRole("button", { name: "Copier le lien" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Nom")).not.toBeInTheDocument();
    expect(api.adminOverview).toHaveBeenCalledTimes(2);
  });

  it("adds a client met elsewhere with only a name, an email and how they came", async () => {
    vi.spyOn(api, "adminAddClient").mockResolvedValue({ customer_id: 9, purchase_id: null, booking_url: null });
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Ajouter un client" }));
    await user.type(screen.getByLabelText("Nom"), "Ange");
    await user.type(screen.getByLabelText("Email"), "ange@x.fr");
    await user.selectOptions(screen.getByLabelText("Mode d’acquisition"), "Autre");
    await user.type(screen.getByLabelText(/Précisez/), "Salon");
    await user.click(screen.getByRole("button", { name: "Ajouter le client" }));
    expect(api.adminAddClient).toHaveBeenCalledWith({
      name: "Ange",
      email: "ange@x.fr",
      acquisition_source: "autre",
      acquisition_detail: "Salon",
      hours: null,
      product_name: undefined,
      amount_cents: 0,
      send_link: false,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Client ajouté au suivi, sans forfait");
  });

  it("shows why a client could not be added and lets the admin cancel", async () => {
    vi.spyOn(api, "adminAddClient").mockRejectedValue(new ApiError(422, "Une erreur est survenue. Veuillez réessayer."));
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Ajouter un client" }));
    await user.type(screen.getByLabelText("Nom"), "C");
    await user.type(screen.getByLabelText("Email"), "c@x.fr");
    await user.selectOptions(screen.getByLabelText("Mode d’acquisition"), "WhatsApp");
    await user.click(screen.getByRole("button", { name: "Ajouter le client" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Une erreur est survenue. Veuillez réessayer.");
    expect(screen.getByRole("button", { name: "Ajouter le client" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByLabelText("Nom")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter un client" })).toBeInTheDocument();
    expect(api.adminOverview).toHaveBeenCalledTimes(1);
  });

  it("cancels a session after confirmation, giving the hour back and notifying the client", async () => {
    const cancel = deferred<{ status: string }>();
    vi.spyOn(api, "adminCancelBooking").mockReturnValue(cancel.promise);
    const user = userEvent.setup();
    renderCockpit("rendez-vous");
    await user.click(await screen.findByRole("button", { name: "Annuler la séance de Jean Dupont" }));
    expect(api.adminCancelBooking).not.toHaveBeenCalled();
    expect(screen.getByText(/l’heure est recréditée au client/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Annuler la séance de Jean Dupont" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annuler la séance de Marie Martin" })).toBeInTheDocument();
    expect(screen.getByLabelText("Envoyer au client son lien pour choisir un autre créneau")).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Confirmer l’annulation" }));
    expect(api.adminCancelBooking).toHaveBeenCalledWith(21, true);
    expect(screen.getByRole("button", { name: "Annulation…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Garder la séance" })).toBeDisabled();

    cancel.resolve({ status: "cancelled" });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Séance de Jean Dupont annulée : l’heure lui a été recréditée et son lien lui a été renvoyé.",
    );
    expect(screen.queryByRole("button", { name: "Confirmer l’annulation" })).not.toBeInTheDocument();
    expect(api.adminOverview).toHaveBeenCalledTimes(2);
  });

  it("cancels a discovery call: no hour to give back, no link to send", async () => {
    const data = overview();
    data.upcoming[0] = { ...data.upcoming[0], kind: "discovery", customer: "Paul Prospect", product: "Appel découverte" };
    vi.mocked(api.adminOverview).mockResolvedValue(data);
    vi.spyOn(api, "adminCancelBooking").mockResolvedValue({ status: "cancelled" });
    const user = userEvent.setup();
    renderCockpit("rendez-vous");
    await user.click(await screen.findByRole("button", { name: "Annuler l’appel découverte de Paul Prospect" }));
    expect(screen.getByText(/Google prévient le prospect/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Envoyer au client son lien pour choisir un autre créneau")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmer l’annulation" }));
    expect(api.adminCancelBooking).toHaveBeenCalledWith(21, false);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Appel découverte de Paul Prospect annulé : Google Agenda a envoyé l’annulation.",
    );
  });

  it("cancels without emailing the client when unticked", async () => {
    vi.spyOn(api, "adminCancelBooking").mockResolvedValue({ status: "cancelled" });
    const user = userEvent.setup();
    renderCockpit("rendez-vous");
    await user.click(await screen.findByRole("button", { name: "Annuler la séance de Marie Martin" }));
    await user.click(screen.getByLabelText("Envoyer au client son lien pour choisir un autre créneau"));
    await user.click(screen.getByRole("button", { name: "Confirmer l’annulation" }));
    expect(api.adminCancelBooking).toHaveBeenCalledWith(22, false);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /^Séance de Marie Martin annulée : l’heure lui a été recréditée\.$/,
    );

    // Reopening resets the choice to "notify".
    await user.click(screen.getByRole("button", { name: "Annuler la séance de Jean Dupont" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Envoyer au client son lien pour choisir un autre créneau")).toBeChecked();
  });

  it("keeps the session when the admin changes their mind or the cancellation fails", async () => {
    vi.spyOn(api, "adminCancelBooking").mockRejectedValue(new ApiError(502, "Rien n’a été annulé : réessayez."));
    const user = userEvent.setup();
    renderCockpit("rendez-vous");
    await user.click(await screen.findByRole("button", { name: "Annuler la séance de Jean Dupont" }));
    await user.click(screen.getByRole("button", { name: "Confirmer l’annulation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rien n’a été annulé : réessayez.");
    expect(screen.getByRole("button", { name: "Confirmer l’annulation" })).toBeEnabled();
    expect(api.adminOverview).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Garder la séance" }));
    expect(screen.queryByText(/l’heure est recréditée au client/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Annuler la séance de Jean Dupont" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Annuler la séance de Jean Dupont" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // previous error cleared
  });

  it("adjusts the hours of a purchase", async () => {
    const saved = deferred<{ hours_purchased: number; hours_booked: number; hours_remaining: number }>();
    vi.spyOn(api, "adminSetHours").mockReturnValue(saved.promise);
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Modifier les heures de Jean Dupont" }));
    const input = screen.getByLabelText("Heures achetées par Jean Dupont");
    expect(input).toHaveValue(5);
    expect(input).toHaveAttribute("min", "1");
    expect(input).toHaveAttribute("max", "100");
    expect(screen.getByRole("button", { name: "Modifier les heures de Paul Rembourse" })).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "2");
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(api.adminSetHours).toHaveBeenCalledWith(1, 2);

    saved.resolve({ hours_purchased: 2, hours_booked: 1, hours_remaining: 1 });
    await vi.waitFor(() => expect(api.adminOverview).toHaveBeenCalledTimes(2));
    expect(screen.queryByLabelText("Heures achetées par Jean Dupont")).not.toBeInTheDocument();
  });

  it("shows why hours could not be changed and lets the admin give up", async () => {
    vi.spyOn(api, "adminSetHours").mockRejectedValue(
      new ApiError(422, "Impossible : 1 h sont déjà réservées ou réalisées pour ce client."),
    );
    const user = userEvent.setup();
    renderCockpit("clients");
    await user.click(await screen.findByRole("button", { name: "Modifier les heures de Jean Dupont" }));
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(api.adminSetHours).toHaveBeenCalledWith(1, 5);
    expect(await screen.findByRole("alert")).toHaveTextContent("Impossible : 1 h sont déjà réservées");
    expect(screen.getByLabelText("Heures achetées par Jean Dupont")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Annuler la modification" }));
    expect(screen.queryByLabelText("Heures achetées par Jean Dupont")).not.toBeInTheDocument();
    expect(api.adminOverview).toHaveBeenCalledTimes(1);
  });

  it("shows one section per tab, kept in the URL, and keeps hidden tabs as they were", async () => {
    const user = userEvent.setup();
    renderCockpit();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.getAttribute("aria-label"))).toEqual([
      "Apprenants",
      "Prochains rendez-vous",
      "Imprimer mon calendrier",
      "Clients",
      "Accord de confidentialité (NDA)",
      "Comptes rendus de séance",
    ]);
    expect(screen.getByRole("tab", { name: "Apprenants" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Apprenants");

    await user.click(screen.getByRole("tab", { name: "Comptes rendus de séance" }));
    expect(window.location.hash).toBe("#comptes-rendus");
    expect(screen.getByRole("heading", { name: "Comptes rendus de séance" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Apprenants" })).not.toBeInTheDocument(); // hidden, not unmounted
    await user.click(screen.getByRole("button", { name: "Coller une transcription" }));
    const pasted = () => within(screen.getByRole("form", { name: /autre réunion/ }));
    await user.type(pasted().getByLabelText("Nom du destinataire"), "Claire");

    await user.click(screen.getByRole("tab", { name: "Clients" }));
    await user.click(screen.getByRole("tab", { name: "Comptes rendus de séance" }));
    expect(pasted().getByLabelText("Nom du destinataire")).toHaveValue("Claire");
  });

  it("opens the tab of the link and moves between tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    renderCockpit("nda");
    const nda = await screen.findByRole("tab", { name: "Accord de confidentialité (NDA)" });
    expect(nda).toHaveAttribute("aria-selected", "true");
    expect(nda).toHaveAttribute("tabindex", "0");
    nda.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Comptes rendus de séance" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Apprenants" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(window.location.hash).toBe("#comptes-rendus");
    await user.keyboard("{Home}{ArrowLeft}");
    expect(window.location.hash).toBe("#comptes-rendus");
  });

  it("an unknown tab in the link opens the first one", async () => {
    renderCockpit("inconnu");
    expect(await screen.findByRole("tab", { name: "Apprenants" })).toHaveAttribute("aria-selected", "true");
  });
});
