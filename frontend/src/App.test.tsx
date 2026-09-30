import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import App from "./App";
import { Alert, Button, HoursSummary } from "./components/Layout";
import { context } from "./test/fixtures";

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.spyOn(api, "context").mockResolvedValue(context());
  vi.spyOn(api, "exchangeCheckout").mockReturnValue(new Promise(() => {}));
  vi.spyOn(api, "adminOverview").mockReturnValue(new Promise(() => {}));
});

describe("routing", () => {
  it("/reservation?session_id=… verifies the payment", () => {
    renderAt("/reservation?session_id=cs_1");
    expect(screen.getByRole("status")).toHaveTextContent("Vérification de votre paiement…");
  });

  it("/reservation/:token opens the booking page", async () => {
    renderAt("/reservation/tok");
    expect(await screen.findByRole("heading", { name: "Votre conseil IA est confirmé" })).toBeInTheDocument();
    expect(api.context).toHaveBeenCalledWith("tok");
  });

  it("/admin opens the dashboard", () => {
    renderAt("/admin");
    expect(screen.getByRole("heading", { name: "Tableau de bord" })).toBeInTheDocument();
  });

  it.each(["/", "/nope", "/reservation/a/b"])("%s is a 404 page pointing to the website", (url) => {
    renderAt(url);
    expect(screen.getByRole("heading", { name: "Page introuvable" })).toBeInTheDocument();
    expect(screen.getByText(/Utilisez le lien de réservation reçu après votre paiement/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "iafluence.fr" })).toHaveAttribute("href", "https://iafluence.fr");
  });
});

describe("layout components", () => {
  it("renders the brand header and footer", () => {
    renderAt("/nope");
    expect(screen.getByRole("banner")).toHaveTextContent("IAfluenceSessions de conseil IA");
    expect(screen.getByRole("contentinfo")).toHaveTextContent("© IAfluence");
  });

  it("Button variants and passthrough props", () => {
    render(
      <>
        <Button onClick={() => {}}>Primaire</Button>
        <Button variant="secondary" className="extra" disabled>
          Secondaire
        </Button>
      </>,
    );
    const primary = screen.getByRole("button", { name: "Primaire" });
    expect(primary).toHaveClass("bg-brand-600");
    const secondary = screen.getByRole("button", { name: "Secondaire" });
    expect(secondary).toHaveClass("bg-white", "extra");
    expect(secondary).not.toHaveClass("bg-brand-600");
    expect(secondary).toBeDisabled();
  });

  it("Alert tones", () => {
    render(
      <>
        <Alert>erreur</Alert>
        <Alert tone="info">info</Alert>
      </>,
    );
    const [error, info] = screen.getAllByRole("alert");
    expect(error).toHaveClass("bg-red-50");
    expect(info).toHaveClass("bg-brand-50");
    expect(info).not.toHaveClass("bg-red-50");
  });

  it("HoursSummary renders a definition list", () => {
    render(<HoursSummary rows={[["A", "1 h"], ["B", "2 h"]]} />);
    expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual(["A", "B"]);
    expect(screen.getAllByRole("definition").map((d) => d.textContent)).toEqual(["1 h", "2 h"]);
  });
});
