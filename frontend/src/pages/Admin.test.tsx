import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { deferred, overview } from "../test/fixtures";
import Admin from "./Admin";

const plain = (s: string | null) => (s ?? "").replace(/\p{Zs}/gu, " ");
const unauthorized = () => new ApiError(401, "Authentification requise.");

beforeEach(() => {
  vi.spyOn(api, "adminOverview").mockResolvedValue(overview());
});

describe("Admin", () => {
  it("shows a spinner then the dashboard KPIs", async () => {
    const data = deferred<ReturnType<typeof overview>>();
    vi.mocked(api.adminOverview).mockReturnValue(data.promise);
    render(<Admin />);
    expect(screen.getByRole("status")).toHaveTextContent("Chargement…");
    data.resolve(overview());

    await screen.findByRole("heading", { name: "Prochains rendez-vous" });
    const kpi = (label: string) => screen.getByText(label).parentElement!;
    expect(plain(kpi("Paiements du mois").textContent)).toBe("Paiements du mois31 500,00 €");
    expect(kpi("Heures vendues")).toHaveTextContent("8 h");
    expect(kpi("Heures vendues").children).toHaveLength(2); // no empty hint line
    expect(kpi("Heures réalisées")).toHaveTextContent("1,5 h");
    expect(kpi("Heures restantes à délivrer")).toHaveTextContent("6,5 h");
    expect(kpi("Heures à planifier")).toHaveTextContent("6 h2 h réservées");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("lists upcoming meetings with an optional Meet link", async () => {
    render(<Admin />);
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
    render(<Admin />);
    const rows = within(await screen.findByRole("table")).getAllByRole("row");
    expect(rows[0]).toHaveTextContent("ClientPrestationAchetéesRéservéesRestantes1re session");
    const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells(rows[1])).toEqual([
      "Jean Dupontjean@example.com",
      "Conseil IA - 5h",
      "5 h",
      "1 h",
      "4 h",
      "Jeudi 8 octobre 2026 · 14:00",
    ]);
    expect(rows[1]).not.toHaveClass("line-through");
    expect(cells(rows[2])[5]).toBe("—");
    expect(rows[2]).toHaveClass("line-through");
    expect(rows).toHaveLength(3);
    expect(screen.queryByText("Aucun client pour le moment.")).not.toBeInTheDocument();
  });

  it("handles empty lists", async () => {
    vi.mocked(api.adminOverview).mockResolvedValue(overview({ upcoming: [], clients: [] }));
    render(<Admin />);
    expect(await screen.findByText("Aucun rendez-vous à venir.")).toBeInTheDocument();
    expect(screen.getByText("Aucun client pour le moment.")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.adminOverview).mockRejectedValue(new ApiError(500, "Une erreur est survenue."));
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Une erreur est survenue.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Administration" })).not.toBeInTheDocument();
  });

  it("asks for the password, then loads the dashboard", async () => {
    vi.mocked(api.adminOverview).mockRejectedValueOnce(unauthorized());
    const login = deferred<{ status: string }>();
    vi.spyOn(api, "adminLogin").mockReturnValue(login.promise);
    const user = userEvent.setup();
    render(<Admin />);

    expect(await screen.findByRole("heading", { name: "Administration" })).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Se connecter" });
    expect(submit).toBeDisabled();
    const password = screen.getByLabelText("Mot de passe");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");

    await user.type(password, "s3cret");
    await user.click(submit);
    expect(api.adminLogin).toHaveBeenCalledWith("s3cret");
    expect(screen.getByRole("button", { name: "Connexion…" })).toBeDisabled();

    login.resolve({ status: "ok" });
    expect(await screen.findByRole("heading", { name: "Tableau de bord" })).toBeInTheDocument();
    expect(api.adminOverview).toHaveBeenCalledTimes(2);
  });

  it("shows a wrong password and lets the user try again", async () => {
    vi.mocked(api.adminOverview).mockRejectedValue(unauthorized());
    vi.spyOn(api, "adminLogin").mockRejectedValue(new ApiError(401, "Mot de passe incorrect."));
    const user = userEvent.setup();
    render(<Admin />);
    await user.type(await screen.findByLabelText("Mot de passe"), "bad");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Mot de passe incorrect.");
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeEnabled();

    const retry = deferred<{ status: string }>();
    vi.mocked(api.adminLogin).mockReturnValueOnce(retry.promise);
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // cleared while retrying
  });

  it("logs out back to the login form, even if the request fails", async () => {
    vi.spyOn(api, "adminLogout").mockRejectedValue(new ApiError(0, "offline"));
    const user = userEvent.setup();
    render(<Admin />);
    await user.click(await screen.findByRole("button", { name: "Déconnexion" }));
    expect(api.adminLogout).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "Administration" })).toBeInTheDocument();
  });

  it("clears a previous load error once the dashboard loads", async () => {
    vi.mocked(api.adminOverview).mockRejectedValueOnce(new ApiError(500, "Erreur serveur."));
    vi.spyOn(api, "adminLogout").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "adminLogin").mockResolvedValue({ status: "ok" });
    const user = userEvent.setup();
    render(<Admin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Erreur serveur.");
    await user.click(screen.getByRole("button", { name: "Déconnexion" }));
    await user.type(await screen.findByLabelText("Mot de passe"), "pw");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("heading", { name: "Prochains rendez-vous" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submits the login form without a page reload", async () => {
    vi.mocked(api.adminOverview).mockRejectedValue(unauthorized());
    vi.spyOn(api, "adminLogin").mockReturnValue(new Promise(() => {}));
    render(<Admin />);
    const form = (await screen.findByLabelText("Mot de passe")).closest("form")!;
    expect(fireEvent.submit(form)).toBe(false); // default navigation prevented
  });
});
