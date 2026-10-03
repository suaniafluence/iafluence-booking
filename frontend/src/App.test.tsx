import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import App from "./App";
import { Alert, Button, HoursSummary } from "./components/Layout";
import { context } from "./test/fixtures";

function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="url">{pathname + search}</p>;
}

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <App />
      <Where />
    </MemoryRouter>,
  );

const url = () => screen.getByTestId("url").textContent;

beforeEach(() => {
  vi.spyOn(api, "context").mockResolvedValue(context());
  vi.spyOn(api, "exchangeCheckout").mockReturnValue(new Promise(() => {}));
  vi.spyOn(api, "adminOverview").mockReturnValue(new Promise(() => {}));
});

describe("routing", () => {
  it("/reservation?session_id=… (Stripe return URL) verifies the payment in the browser language", () => {
    renderAt("/reservation?session_id=cs_1");
    expect(screen.getByRole("status")).toHaveTextContent("Vérification de votre paiement…");
    expect(api.exchangeCheckout).toHaveBeenCalledWith("cs_1");
  });

  it("/es/reservation?session_id=… verifies the payment in Spanish", () => {
    renderAt("/es/reservation?session_id=cs_1");
    expect(screen.getByRole("status")).toHaveTextContent("Verificando su pago…");
  });

  it("/fr/reservation/:token opens the booking page", async () => {
    renderAt("/fr/reservation/tok");
    expect(await screen.findByRole("heading", { name: "Votre conseil IA est confirmé" })).toBeInTheDocument();
    expect(api.context).toHaveBeenCalledWith("tok");
    expect(document.documentElement.lang).toBe("fr");
    expect(document.title).toBe("IAfluence — Réservation");
  });

  it.each([
    ["en", "Your AI consulting is confirmed", "IAfluence — Booking"],
    ["es", "Su asesoría en IA está confirmada", "IAfluence — Reserva"],
  ])("/%s/reservation/:token is translated", async (lang, heading, title) => {
    renderAt(`/${lang}/reservation/tok`);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe(lang);
    expect(document.title).toBe(title);
  });

  it("old /reservation/:token links move to the purchase language", async () => {
    vi.mocked(api.context).mockResolvedValue(context({ locale: "en" }));
    renderAt("/reservation/tok");
    expect(screen.getByRole("status")).toHaveTextContent("Chargement de votre réservation…");
    expect(await screen.findByRole("heading", { name: "Your AI consulting is confirmed" })).toBeInTheDocument();
    expect(url()).toBe("/en/reservation/tok");
  });

  it.each([
    ["an unexpected language", () => Promise.resolve(context({ locale: "de" }))],
    ["an invalid link", () => Promise.reject(new ApiError(404, "x", "invalid_token"))],
  ])("old links fall back to the browser language for %s", async (_, answer) => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["es-CL", "en"]);
    vi.mocked(api.context).mockImplementationOnce(answer);
    renderAt("/reservation/tok");
    await waitFor(() => expect(url()).toBe("/es/reservation/tok"));
  });

  it("switching language keeps the page and the booking step", async () => {
    const user = userEvent.setup();
    renderAt("/fr/reservation/tok");
    await screen.findByRole("heading", { name: "Votre conseil IA est confirmé" });
    expect(screen.getByRole("navigation", { name: "Langue" })).toHaveTextContent("FRENES");
    expect(screen.getByRole("link", { name: "Français" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: "English" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "English" })).toHaveAttribute("hreflang", "en");

    await user.click(screen.getByRole("link", { name: "Español" }));
    expect(await screen.findByRole("heading", { name: "Su asesoría en IA está confirmada" })).toBeInTheDocument();
    expect(url()).toBe("/es/reservation/tok");
    expect(screen.getByRole("navigation", { name: "Idioma" })).toBeInTheDocument();
    expect(api.context).toHaveBeenCalledTimes(1); // same page, not reloaded
  });

  it("the language switcher keeps the query string", () => {
    renderAt("/fr/reservation?session_id=cs_1");
    expect(screen.getByRole("link", { name: "English" })).toHaveAttribute("href", "/en/reservation?session_id=cs_1");
  });

  it("/admin opens the configuration, in French, without language switcher", () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-GB"]);
    vi.spyOn(api, "authMe").mockReturnValue(new Promise(() => {}));
    renderAt("/admin");
    expect(screen.getByRole("heading", { name: "Administration" })).toBeInTheDocument();
    expect(api.authMe).toHaveBeenCalledWith("admin");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("/consultant opens the cockpit", () => {
    renderAt("/consultant");
    expect(screen.getByRole("heading", { name: "Cockpit consultant" })).toBeInTheDocument();
  });

  it("/consultant/apprenants/:id opens a learner", () => {
    vi.spyOn(api, "learner").mockReturnValue(new Promise(() => {}));
    renderAt("/consultant/apprenants/7");
    expect(api.learner).toHaveBeenCalledWith(7);
    expect(screen.getByRole("link", { name: "← Cockpit" })).toHaveAttribute("href", "/consultant");
  });

  it("/ offers the two staff areas", async () => {
    const user = userEvent.setup();
    renderAt("/");
    expect(screen.getByRole("link", { name: /Administration/ })).toHaveAttribute("href", "/admin");
    await user.click(screen.getByRole("link", { name: /Espace consultant/ }));
    expect(url()).toBe("/consultant");
  });

  it.each(["/nope", "/reservation/a/b", "/de/reservation/tok", "/fr/reservation/a/b"])(
    "%s is a 404 page pointing to the website",
    (path) => {
      renderAt(path);
      expect(screen.getByRole("heading", { name: "Page introuvable" })).toBeInTheDocument();
      expect(screen.getByText(/Utilisez le lien de réservation reçu après votre paiement/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "iafluence.fr" })).toHaveAttribute("href", "https://iafluence.fr");
      expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
      expect(api.context).not.toHaveBeenCalled();
    },
  );

  it("the 404 page follows the browser language", () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["de-DE", "en-US"]);
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("AI consulting sessions");
  });

  it("/en/decouverte opens the free discovery call page", async () => {
    vi.spyOn(api, "discoveryInfo").mockResolvedValue({ consultant_name: "Suan", timezone: "Europe/Paris", duration_min: 30, nda_available: false });
    vi.spyOn(api, "discoveryAvailability").mockResolvedValue({ slots: [] });
    renderAt("/en/decouverte");
    expect(await screen.findByRole("heading", { name: "Let’s talk about your AI projects in 30 minutes" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });

  it("/decouverte moves to the browser language", async () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["es-CL"]);
    vi.spyOn(api, "discoveryInfo").mockReturnValue(new Promise(() => {}));
    renderAt("/decouverte");
    await waitFor(() => expect(url()).toBe("/es/decouverte"));
  });

  it("falls back to French when the browser has no supported language", () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue([]);
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page introuvable" })).toBeInTheDocument();
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
