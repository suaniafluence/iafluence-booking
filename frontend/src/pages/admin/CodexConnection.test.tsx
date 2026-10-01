import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../api";
import { codexLogin, codexStatus, deferred } from "../../test/fixtures";
import { CodexConnection, POLL_MS } from "./CodexConnection";

beforeEach(() => {
  vi.spyOn(api, "adminCodexStatus").mockResolvedValue(codexStatus());
});

afterEach(() => {
  vi.useRealTimers();
});

/** Fake timers for the status polling; user-event advances them while it waits. */
function withFakeTimers() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

const tick = () => act(() => vi.advanceTimersByTimeAsync(POLL_MS));

describe("CodexConnection", () => {
  it("shows the check in progress, then the disconnected state", async () => {
    const status = deferred<ReturnType<typeof codexStatus>>();
    vi.mocked(api.adminCodexStatus).mockReturnValue(status.promise);
    render(<CodexConnection />);
    expect(screen.getByRole("heading", { name: "Connexion Codex" })).toBeInTheDocument();
    expect(screen.getByText("Vérification de la connexion…")).toBeInTheDocument();
    status.resolve(codexStatus());
    expect(await screen.findByText("Non connecté")).toBeInTheDocument();
    expect(screen.getByText("Les résumés échoueront tant que Codex n’est pas connecté.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connecter Codex" })).toBeEnabled();
    expect(screen.queryByText("Vérification de la connexion…")).not.toBeInTheDocument();
  });

  it("shows the connected account and disconnects", async () => {
    vi.mocked(api.adminCodexStatus).mockResolvedValue(
      codexStatus({ state: "connected", email: "suan@iafluence.fr", plan: "plus" }),
    );
    const logout = deferred<{ state: "disconnected" }>();
    vi.spyOn(api, "adminCodexLogout").mockReturnValue(logout.promise);
    const user = userEvent.setup();
    render(<CodexConnection />);
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
    expect(screen.getByText(/Compte ChatGPT/)).toHaveTextContent("Compte ChatGPT : suan@iafluence.fr · forfait plus");

    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus());
    await user.click(screen.getByRole("button", { name: "Déconnecter" }));
    expect(screen.getByRole("button", { name: "Déconnecter" })).toBeDisabled();
    logout.resolve({ state: "disconnected" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Codex est déconnecté.");
    expect(await screen.findByText("Non connecté")).toBeInTheDocument();
    expect(api.adminCodexStatus).toHaveBeenCalledTimes(2);
  });

  it("shows an account without email or plan", async () => {
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ state: "connected" }));
    render(<CodexConnection />);
    expect(await screen.findByText(/Compte ChatGPT/)).toHaveTextContent(/^Compte ChatGPT : inconnu$/);
  });

  it("offers to reconnect an expired session", async () => {
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ state: "expired" }));
    render(<CodexConnection />);
    expect(await screen.findByText("Connexion expirée")).toBeInTheDocument();
    expect(screen.getByText("La session ChatGPT a pris fin : reconnectez Codex.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnecter Codex" })).toBeInTheDocument();
  });

  it("explains when the codex service is not installed", async () => {
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ state: "not_configured" }));
    render(<CodexConnection />);
    expect(await screen.findByText("Service Codex non installé")).toBeInTheDocument();
    expect(screen.getByText(/Démarrez le service/)).toHaveTextContent(
      "Démarrez le service codex sur le serveur (COMPOSE_PROFILES) et renseignez CODEX_APP_SERVER_URL et CODEX_WS_TOKEN : le bouton « Connecter Codex » apparaîtra ici.",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reports an unreachable app-server and retries", async () => {
    vi.mocked(api.adminCodexStatus).mockResolvedValue(
      codexStatus({ state: "unavailable", detail: "codex app-server injoignable (ConnectionRefusedError)" }),
    );
    const user = userEvent.setup();
    render(<CodexConnection />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Le service Codex est injoignable : codex app-server injoignable (ConnectionRefusedError)",
    );
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ state: "connected" }));
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
  });

  it("shows a status load error", async () => {
    vi.mocked(api.adminCodexStatus).mockRejectedValue(new ApiError(0, "Connexion impossible."));
    render(<CodexConnection />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Connexion impossible.");
    expect(screen.queryByText("Vérification de la connexion…")).not.toBeInTheDocument();
  });

  it("runs the device login until OpenAI confirms it", async () => {
    const user = withFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const start = deferred<ReturnType<typeof codexLogin>>();
    vi.spyOn(api, "adminCodexLogin").mockReturnValue(start.promise);
    vi.spyOn(api, "adminCodexLoginStatus").mockResolvedValue(codexLogin());
    render(<CodexConnection />);

    await user.click(await screen.findByRole("button", { name: "Connecter Codex" }));
    expect(screen.getByRole("button", { name: "Connexion…" })).toBeDisabled();
    start.resolve(codexLogin());

    expect(await screen.findByText("https://auth.openai.com/codex/device")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ouvrir OpenAI" })).toHaveAttribute("href", "https://auth.openai.com/codex/device");
    expect(screen.getByRole("link", { name: "Ouvrir OpenAI" })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Ouvrir OpenAI" })).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByLabelText("Code de connexion")).toHaveTextContent("ABCD-1234");
    expect(screen.getByRole("status")).toHaveTextContent("En attente de la validation… Le code expire à 08:15.");
    expect(screen.queryByRole("button", { name: "Connecter Codex" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copier l’adresse de connexion" }));
    expect(writeText).toHaveBeenLastCalledWith("https://auth.openai.com/codex/device");
    await user.click(screen.getByRole("button", { name: "Copier le code" }));
    expect(writeText).toHaveBeenLastCalledWith("ABCD-1234");
    expect(screen.getAllByRole("button", { name: /Copier/ }).map((b) => b.textContent)).toEqual(["Copié", "Copié"]);

    // Polled every few seconds, not before.
    expect(api.adminCodexLoginStatus).not.toHaveBeenCalled();
    await tick();
    expect(api.adminCodexLoginStatus).toHaveBeenCalledTimes(1);
    expect(api.adminCodexLoginStatus).toHaveBeenCalledWith(3);
    await tick();
    expect(api.adminCodexLoginStatus).toHaveBeenCalledTimes(2);

    vi.mocked(api.adminCodexLoginStatus).mockResolvedValue(codexLogin({ status: "COMPLETED", user_code: null }));
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ state: "connected", email: "suan@iafluence.fr" }));
    await tick();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Codex est connecté : les résumés utiliseront votre forfait ChatGPT.",
    );
    expect(await screen.findByText("Connecté")).toBeInTheDocument();
    expect(screen.queryByLabelText("Code de connexion")).not.toBeInTheDocument();

    await tick();
    expect(api.adminCodexLoginStatus).toHaveBeenCalledTimes(3); // polling stopped
  });

  it("keeps polling through network hiccups", async () => {
    withFakeTimers();
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ pending_login: codexLogin({ id: 9 }) }));
    vi.spyOn(api, "adminCodexLoginStatus").mockRejectedValueOnce(new ApiError(0, "x"));
    render(<CodexConnection />);
    // A login still pending after a page reload is resumed.
    expect(await screen.findByLabelText("Code de connexion")).toBeInTheDocument();
    await tick();
    vi.mocked(api.adminCodexLoginStatus).mockResolvedValue(codexLogin({ id: 9 }));
    await tick();
    expect(api.adminCodexLoginStatus).toHaveBeenCalledTimes(2);
    expect(api.adminCodexLoginStatus).toHaveBeenLastCalledWith(9);
  });

  it.each([
    [codexLogin({ status: "EXPIRED" }), "Le code a expiré avant d’être validé. Relancez la connexion."],
    [codexLogin({ status: "DENIED", error: "access_denied" }), "La connexion a été refusée sur la page OpenAI."],
    [codexLogin({ status: "ERROR", error: "réseau" }), "La connexion a échoué : réseau"],
    [codexLogin({ status: "ERROR" }), "La connexion a échoué"],
    [codexLogin({ status: "CANCELLED" }), "Connexion annulée."],
  ])("explains a login that did not complete (%#)", async (outcome, message) => {
    withFakeTimers();
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ pending_login: codexLogin() }));
    vi.spyOn(api, "adminCodexLoginStatus").mockResolvedValue(outcome);
    render(<CodexConnection />);
    await screen.findByLabelText("Code de connexion");
    await tick();
    expect(await screen.findByRole("alert")).toHaveTextContent(new RegExp(`^${message}$`));
    expect(screen.queryByLabelText("Code de connexion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connecter Codex" })).toBeInTheDocument();
    expect(api.adminCodexStatus).toHaveBeenCalledTimes(1);
  });

  it("cancels a pending login", async () => {
    const user = withFakeTimers();
    vi.mocked(api.adminCodexStatus).mockResolvedValue(codexStatus({ pending_login: codexLogin() }));
    vi.spyOn(api, "adminCodexLoginStatus").mockResolvedValue(codexLogin());
    vi.spyOn(api, "adminCodexCancelLogin").mockResolvedValue(codexLogin({ status: "CANCELLED" }));
    render(<CodexConnection />);
    await user.click(await screen.findByRole("button", { name: "Annuler la connexion" }));
    expect(api.adminCodexCancelLogin).toHaveBeenCalledWith(3);
    expect(await screen.findByRole("alert")).toHaveTextContent("Connexion annulée.");
    expect(screen.getByRole("button", { name: "Connecter Codex" })).toBeInTheDocument();
    await tick();
    expect(api.adminCodexLoginStatus).not.toHaveBeenCalled();
  });

  it("shows why the login could not start", async () => {
    vi.spyOn(api, "adminCodexLogin").mockRejectedValue(new ApiError(502, "Le service Codex est injoignable : x"));
    const user = userEvent.setup();
    render(<CodexConnection />);
    await user.click(await screen.findByRole("button", { name: "Connecter Codex" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Le service Codex est injoignable : x");
    await waitFor(() => expect(screen.getByRole("button", { name: "Connecter Codex" })).toBeEnabled());
  });
});
