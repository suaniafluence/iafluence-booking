import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type PlatformSettings, type StaffUser } from "../api";
import { SIGN_IN_ERRORS } from "../components/StaffLogin";
import { codexStatus, deferred, firefliesStatus } from "../test/fixtures";
import Admin from "./Admin";

const unauthorized = () => new ApiError(401, "Authentification requise.");

const staff = (over: Partial<StaffUser> = {}): StaffUser => ({
  id: 1,
  email: "suan@iafluence.fr",
  name: "Suan Tay",
  is_admin: true,
  is_consultant: true,
  active: true,
  google_linked: true,
  last_login_at: null,
  ...over,
});

const settings = (over: Partial<PlatformSettings> = {}): PlatformSettings => ({
  send_without_review: false,
  reminder_enabled: true,
  reminder_after_days: 21,
  reminder_auto_send: false,
  hide_after_days: 60,
  ...over,
});

beforeEach(() => {
  window.history.replaceState(null, "", "/admin");
  vi.spyOn(api, "authMe").mockResolvedValue({ id: 1, email: "suan@iafluence.fr", name: "Suan Tay", role: "admin" });
  vi.spyOn(api, "authMethods").mockResolvedValue({ google: true, password: true });
  vi.spyOn(api, "adminUsers").mockResolvedValue({ users: [staff()], google_enabled: true });
  vi.spyOn(api, "adminSettings").mockResolvedValue(settings());
  vi.spyOn(api, "adminCodexStatus").mockResolvedValue(codexStatus({ state: "connected", email: "suan@iafluence.fr" }));
  vi.spyOn(api, "adminFirefliesStatus").mockResolvedValue(firefliesStatus());
});

describe("Admin sign-in", () => {
  it("offers Google and the password fallback, then loads the configuration", async () => {
    vi.mocked(api.authMe).mockRejectedValueOnce(unauthorized());
    const login = deferred<{ status: string }>();
    vi.spyOn(api, "adminLogin").mockReturnValue(login.promise);
    const user = userEvent.setup();
    render(<Admin />);

    expect(await screen.findByRole("link", { name: "Se connecter avec Google" })).toHaveAttribute(
      "href",
      "/api/auth/google/start?role=admin",
    );
    expect(screen.getByRole("heading", { name: "Administration" })).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Se connecter" });
    expect(submit).toBeDisabled();
    const password = screen.getByLabelText("Mot de passe de secours");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    await user.type(password, "s3cret");
    await user.click(submit);
    expect(api.adminLogin).toHaveBeenCalledWith("s3cret");
    expect(screen.getByRole("button", { name: "Connexion…" })).toBeDisabled();
    login.resolve({ status: "ok" });
    expect(await screen.findByRole("heading", { name: "Comptes et rôles" })).toBeInTheDocument();
    expect(api.authMe).toHaveBeenCalledTimes(2);
  });

  it("shows a wrong password and lets the user try again", async () => {
    vi.mocked(api.authMe).mockRejectedValue(unauthorized());
    vi.spyOn(api, "adminLogin").mockRejectedValue(new ApiError(401, "Mot de passe incorrect."));
    const user = userEvent.setup();
    render(<Admin />);
    await user.type(await screen.findByLabelText("Mot de passe de secours"), "bad");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Mot de passe incorrect.");
    vi.mocked(api.adminLogin).mockReturnValueOnce(new Promise(() => {}));
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submits the password without a page reload", async () => {
    vi.mocked(api.authMe).mockRejectedValue(unauthorized());
    vi.spyOn(api, "adminLogin").mockReturnValue(new Promise(() => {}));
    render(<Admin />);
    const form = (await screen.findByLabelText("Mot de passe de secours")).closest("form")!;
    expect(fireEvent.submit(form)).toBe(false);
  });

  it.each(Object.entries(SIGN_IN_ERRORS))("explains a refused Google sign-in (%s)", async (code, message) => {
    window.history.replaceState(null, "", `/admin?erreur=${code}`);
    vi.mocked(api.authMe).mockRejectedValue(unauthorized());
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("an unknown error code still says the sign-in failed", async () => {
    window.history.replaceState(null, "", "/admin?erreur=bizarre");
    vi.mocked(api.authMe).mockRejectedValue(unauthorized());
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("La connexion a échoué.");
  });

  it("without Google nor password, says sign-in is not configured", async () => {
    vi.mocked(api.authMe).mockRejectedValue(new ApiError(403, "Accès retiré."));
    vi.mocked(api.authMethods).mockResolvedValue({ google: false, password: false });
    render(<Admin />);
    expect(await screen.findByText("La connexion Google n’est pas configurée sur ce serveur.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Se connecter avec Google" })).not.toBeInTheDocument();
  });

  it("if the methods cannot be read, Google and the password are offered", async () => {
    vi.mocked(api.authMe).mockRejectedValue(unauthorized());
    vi.mocked(api.authMethods).mockRejectedValue(new ApiError(0, "offline"));
    render(<Admin />);
    expect(await screen.findByRole("link", { name: "Se connecter avec Google" })).toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe de secours")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.authMe).mockRejectedValue(new ApiError(500, "Erreur serveur."));
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Erreur serveur.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("logs out back to the sign-in page, even if the request fails", async () => {
    vi.spyOn(api, "authLogout").mockRejectedValue(new ApiError(0, "offline"));
    const user = userEvent.setup();
    render(<Admin />);
    await user.click(await screen.findByRole("button", { name: "Déconnexion" }));
    expect(api.authLogout).toHaveBeenCalledWith("admin");
    expect(await screen.findByRole("link", { name: "Se connecter avec Google" })).toBeInTheDocument();
  });

  it("links to the cockpit and says who is signed in", async () => {
    render(<Admin />);
    expect(await screen.findByText("Connecté : suan@iafluence.fr")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cockpit consultant" })).toHaveAttribute("href", "/consultant");
  });

  it("the password session has no email", async () => {
    vi.mocked(api.authMe).mockResolvedValue({ id: null, email: "", name: "Administrateur", role: "admin" });
    render(<Admin />);
    expect(await screen.findByText("Connecté : mot de passe de secours")).toBeInTheDocument();
  });
});

describe("Staff accounts", () => {
  it("lists accounts with their roles", async () => {
    vi.mocked(api.adminUsers).mockResolvedValue({
      users: [staff(), staff({ id: 2, email: "claire@exemple.fr", name: "", is_admin: false, google_linked: false, active: false })],
      google_enabled: false,
    });
    render(<Admin />);
    const rows = within((await screen.findAllByRole("table"))[0]).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("Suan Taysuan@iafluence.fr");
    expect(screen.getByRole("checkbox", { name: "Administrateur pour suan@iafluence.fr" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Administrateur pour claire@exemple.fr" })).not.toBeChecked();
    expect(rows[2]).toHaveTextContent("Pas encore connecté");
    expect(rows[2]).toHaveClass("text-slate-400");
    expect(screen.getByRole("checkbox", { name: "Compte actif : claire@exemple.fr" })).not.toBeChecked();
    expect(screen.getByText(/La connexion Google n’est pas configurée/)).toBeInTheDocument();
  });

  it("changes a role, deactivates, unlinks Google, then reloads", async () => {
    vi.spyOn(api, "adminUpdateUser").mockResolvedValue(staff());
    const user = userEvent.setup();
    render(<Admin />);
    await user.click(await screen.findByRole("checkbox", { name: "Consultant pour suan@iafluence.fr" }));
    expect(api.adminUpdateUser).toHaveBeenLastCalledWith(1, { is_consultant: false });
    await user.click(screen.getByRole("checkbox", { name: "Administrateur pour suan@iafluence.fr" }));
    expect(api.adminUpdateUser).toHaveBeenLastCalledWith(1, { is_admin: false });
    await user.click(screen.getByRole("checkbox", { name: "Compte actif : suan@iafluence.fr" }));
    expect(api.adminUpdateUser).toHaveBeenLastCalledWith(1, { active: false });
    await user.click(screen.getByRole("button", { name: "Délier le compte Google" }));
    expect(api.adminUpdateUser).toHaveBeenLastCalledWith(1, { unlink_google: true });
    expect(api.adminUsers).toHaveBeenCalledTimes(5);
  });

  it("shows why a change was refused", async () => {
    vi.spyOn(api, "adminUpdateUser").mockRejectedValue(new ApiError(409, "Impossible : ce serait le dernier administrateur."));
    const user = userEvent.setup();
    render(<Admin />);
    await user.click(await screen.findByRole("checkbox", { name: "Compte actif : suan@iafluence.fr" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("dernier administrateur");
  });

  it("adds an account", async () => {
    const added = deferred<StaffUser>();
    vi.spyOn(api, "adminAddUser").mockReturnValue(added.promise);
    const user = userEvent.setup();
    render(<Admin />);
    const add = await screen.findByRole("button", { name: "Ajouter le compte" });
    expect(add).toBeDisabled();
    await user.type(screen.getByLabelText("Adresse Google"), "claire@exemple.fr");
    await user.type(screen.getByLabelText("Nom"), "Claire");
    await user.click(screen.getByRole("checkbox", { name: "Administrateur" }));
    await user.click(add);
    expect(api.adminAddUser).toHaveBeenCalledWith({ email: "claire@exemple.fr", name: "Claire", is_admin: true, is_consultant: true });
    expect(screen.getByRole("button", { name: "Ajout…" })).toBeDisabled();
    added.resolve(staff({ id: 2 }));
    expect(await screen.findByRole("button", { name: "Ajouter le compte" })).toBeDisabled();
    expect(screen.getByLabelText("Adresse Google")).toHaveValue("");
    expect(api.adminUsers).toHaveBeenCalledTimes(2);
  });

  it("shows why an account could not be added", async () => {
    vi.spyOn(api, "adminAddUser").mockRejectedValue(new ApiError(409, "Cette adresse a déjà un compte."));
    const user = userEvent.setup();
    render(<Admin />);
    await user.type(await screen.findByLabelText("Adresse Google"), "suan@iafluence.fr");
    await user.click(screen.getByRole("checkbox", { name: "Consultant" }));
    await user.click(screen.getByRole("button", { name: "Ajouter le compte" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cette adresse a déjà un compte.");
    expect(api.adminAddUser).toHaveBeenCalledWith(expect.objectContaining({ is_consultant: false }));
  });

  it("shows a list error", async () => {
    vi.mocked(api.adminUsers).mockRejectedValue(new ApiError(500, "Liste indisponible."));
    render(<Admin />);
    expect(await screen.findByText("Liste indisponible.")).toBeInTheDocument();
  });
});

describe("Reminder settings", () => {
  it("toggles reminders and auto-send", async () => {
    vi.spyOn(api, "adminUpdateSettings").mockResolvedValue(settings({ reminder_enabled: false }));
    const user = userEvent.setup();
    render(<Admin />);
    await user.click(await screen.findByRole("checkbox", { name: "Relancer les apprenants inactifs" }));
    expect(api.adminUpdateSettings).toHaveBeenLastCalledWith({ reminder_enabled: false });
    expect(await screen.findByText("Réglages enregistrés.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Relancer les apprenants inactifs" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Envoyer la relance directement (sans brouillon)" }));
    expect(api.adminUpdateSettings).toHaveBeenLastCalledWith({ reminder_auto_send: true });
  });

  it("saves the delays, or says why not", async () => {
    vi.spyOn(api, "adminUpdateSettings")
      .mockRejectedValueOnce(new ApiError(422, "Le délai de masquage doit être plus long que celui de la relance."))
      .mockResolvedValueOnce(settings({ reminder_after_days: 30, hide_after_days: 90 }));
    const user = userEvent.setup();
    render(<Admin />);
    const after = await screen.findByLabelText("Relance après (jours sans séance)");
    expect(after).toHaveValue(21);
    await user.clear(after);
    await user.type(after, "70");
    await user.click(screen.getByRole("button", { name: "Enregistrer les délais" }));
    expect(api.adminUpdateSettings).toHaveBeenLastCalledWith({ reminder_after_days: 70, hide_after_days: 60 });
    expect(await screen.findByRole("alert")).toHaveTextContent("Le délai de masquage");
    await user.click(screen.getByRole("button", { name: "Enregistrer les délais" }));
    expect(await screen.findByText("Réglages enregistrés.")).toBeInTheDocument();
    expect(screen.getByLabelText("Masqué du cockpit après (jours)")).toHaveValue(90);
    expect(screen.queryByRole("alert", { name: /délai/ })).not.toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.adminSettings).mockRejectedValue(new ApiError(500, "Réglages indisponibles."));
    render(<Admin />);
    expect(await screen.findByText("Réglages indisponibles.")).toBeInTheDocument();
  });
});
