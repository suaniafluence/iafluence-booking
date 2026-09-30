import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { confirmed, context, deferred, slots } from "../test/fixtures";
import Reservation from "./Reservation";

function renderAt(token = "tok123") {
  return render(
    <MemoryRouter initialEntries={[`/reservation/${token}`]}>
      <Link to="/reservation/tok999">other link</Link>
      <Routes>
        <Route path="/reservation/:token" element={<Reservation />} />
      </Routes>
    </MemoryRouter>,
  );
}

const summary = () => {
  const rows = screen.getAllByRole("term").map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
  return Object.fromEntries(rows);
};

async function goToPicker(user = userEvent.setup()) {
  renderAt();
  await user.click(await screen.findByRole("button", { name: "Choisir mon créneau" }));
  await screen.findByRole("tablist", { name: "Jours disponibles" });
  return user;
}

beforeEach(() => {
  vi.spyOn(api, "context").mockResolvedValue(context());
  vi.spyOn(api, "availability").mockResolvedValue({ slots });
});

describe("Reservation", () => {
  it("shows a spinner, then the welcome step with the hours summary", async () => {
    const ctx = deferred<ReturnType<typeof context>>();
    vi.mocked(api.context).mockReturnValue(ctx.promise);
    renderAt("tok123");
    expect(screen.getByRole("status")).toHaveTextContent("Chargement de votre réservation…");
    expect(api.context).toHaveBeenCalledWith("tok123");
    ctx.resolve(context());

    expect(await screen.findByRole("heading", { name: "Votre conseil IA est confirmé" })).toBeInTheDocument();
    expect(summary()).toEqual({
      Prestation: "Conseil IA",
      "Heures achetées": "5 h",
      "Première session": "1 h",
      "Heures restantes après cette session": "4 h",
    });
    expect(api.availability).not.toHaveBeenCalled();
  });

  it("says so when every hour has been used", async () => {
    vi.mocked(api.context).mockResolvedValue(
      context({ purchase: { product_name: "x", hours_purchased: 3, hours_booked: 3, hours_remaining: 0 } }),
    );
    renderAt();
    expect(await screen.findByRole("heading", { name: "Toutes vos heures ont été utilisées" })).toBeInTheDocument();
    expect(screen.getByText(/poursuivre avec de nouvelles heures de conseil/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "iafluence.fr" })).toHaveAttribute("href", "https://iafluence.fr");
    expect(summary()).toEqual({ "Heures achetées": "3 h", "Heures restantes": "0 h" });
    expect(screen.queryByRole("button", { name: "Choisir mon créneau" })).not.toBeInTheDocument();
  });

  it("offers the next session once the previous one is over", async () => {
    vi.mocked(api.context).mockResolvedValue(
      context({ purchase: { product_name: "x", hours_purchased: 5, hours_booked: 2, hours_remaining: 3 } }),
    );
    const user = userEvent.setup();
    renderAt();
    expect(await screen.findByRole("heading", { name: "Réservez votre prochaine session" })).toBeInTheDocument();
    expect(screen.getByText("Conseil IA", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Choisissez le créneau de votre prochaine session de conseil de 1 heure.")).toBeInTheDocument();
    expect(screen.queryByText("Votre paiement a bien été reçu.")).not.toBeInTheDocument();
    expect(summary()).toEqual({
      Prestation: "Conseil IA",
      "Heures achetées": "5 h",
      "Prochaine session": "1 h",
      "Heures restantes après cette session": "2 h",
    });
    await user.click(screen.getByRole("button", { name: "Choisir mon créneau" }));
    expect(await screen.findByRole("heading", { name: "Choisissez votre créneau" })).toBeInTheDocument();
  });

  it("offers the last hour as the next session", async () => {
    vi.mocked(api.context).mockResolvedValue(
      context({ purchase: { product_name: "x", hours_purchased: 2, hours_booked: 1, hours_remaining: 1 } }),
    );
    renderAt();
    await screen.findByRole("heading", { name: "Réservez votre prochaine session" });
    expect(summary()["Heures restantes après cette session"]).toBe("0 h");
  });

  it("shows the error page for an invalid or revoked link", async () => {
    vi.mocked(api.context).mockRejectedValue(new ApiError(404, "Ce lien de réservation est invalide ou a expiré."));
    renderAt();
    expect(await screen.findByRole("heading", { name: "Lien de réservation indisponible" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Ce lien de réservation est invalide ou a expiré.");
  });

  it("goes straight to the confirmation when the session is already booked", async () => {
    vi.mocked(api.context).mockResolvedValue(
      context({
        booking: { start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T15:00:00+02:00", meet_url: null },
        purchase: { product_name: "x", hours_purchased: 1, hours_booked: 1, hours_remaining: 0 },
      }),
    );
    renderAt();
    const heading = await screen.findByRole("heading", { name: "Rendez-vous confirmé" });
    expect(screen.getByText("Jeudi 8 octobre 2026")).toBeInTheDocument();
    expect(screen.getByText("14:00 - 15:00 · Conseil IA avec Suan Tay")).toBeInTheDocument();
    expect(within(heading.closest("section")!).queryByRole("link")).not.toBeInTheDocument();
    expect(summary()).toEqual({ "Heures achetées": "1 h", "Heures planifiées": "1 h", "Heures restantes": "0 h" });
    expect(screen.queryByText(/séance suivante/)).not.toBeInTheDocument();
  });

  it("groups slots by day and switches days", async () => {
    const user = await goToPicker();
    expect(api.availability).toHaveBeenCalledWith("tok123");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Jeu8oct.", "Ven9oct."]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Jeudi 8 octobre");
    expect(screen.getAllByRole("button", { name: /^\d\d:\d\d$/ }).map((b) => b.textContent)).toEqual(["14:00", "16:00"]);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(tabs[1]);
    expect(screen.getByRole("tab", { name: /Ven/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Vendredi 9 octobre");
    expect(screen.getAllByRole("button", { name: /^\d\d:\d\d$/ }).map((b) => b.textContent)).toEqual(["09:00"]);
  });

  it("tells the customer when nothing is available", async () => {
    vi.mocked(api.availability).mockResolvedValue({ slots: [] });
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole("button", { name: "Choisir mon créneau" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Aucun créneau n’est disponible pour le moment.");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("offers a retry when availability fails", async () => {
    vi.mocked(api.availability)
      .mockRejectedValueOnce(new ApiError(503, "Les disponibilités sont momentanément indisponibles."))
      .mockResolvedValueOnce({ slots });
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole("button", { name: "Choisir mon créneau" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Les disponibilités sont momentanément indisponibles.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByRole("tablist")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.availability).toHaveBeenCalledTimes(2);
  });

  it("shows a spinner while slots load", async () => {
    vi.mocked(api.availability).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderAt();
    await user.click(await screen.findByRole("button", { name: "Choisir mon créneau" }));
    expect(screen.getByRole("status")).toHaveTextContent("Recherche des disponibilités…");
  });

  it("books a slot end to end", async () => {
    const book = deferred<ReturnType<typeof confirmed>>();
    vi.spyOn(api, "book").mockReturnValue(book.promise);
    const user = await goToPicker();
    await user.click(screen.getByRole("tab", { name: /Ven/ }));
    await user.click(screen.getByRole("button", { name: "09:00" }));

    expect(screen.getByRole("heading", { name: "Votre rendez-vous" })).toBeInTheDocument();
    expect(screen.getByText("Vendredi 9 octobre 2026")).toBeInTheDocument();
    expect(screen.getByText("09:00 - 10:00")).toBeInTheDocument();
    expect(screen.getByText("Conseil IA avec Suan Tay")).toBeInTheDocument();
    expect(screen.getByText("jean@example.com")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    expect(api.book).toHaveBeenCalledWith("tok123", "2026-10-09T09:00:00+02:00");
    expect(screen.getByRole("button", { name: "Confirmation…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Changer de créneau" })).toBeDisabled();

    book.resolve(confirmed());
    expect(await screen.findByRole("heading", { name: "Rendez-vous confirmé" })).toBeInTheDocument();
    const meet = screen.getByRole("link", { name: "https://meet.google.com/abc-defg-hij" });
    expect(meet).toHaveAttribute("href", "https://meet.google.com/abc-defg-hij");
    expect(meet).toHaveAttribute("target", "_blank");
    expect(meet).toHaveAttribute("rel", "noreferrer");
    expect(summary()).toEqual({ "Heures achetées": "5 h", "Heures planifiées": "1 h", "Heures restantes": "4 h" });
    expect(
      screen.getByText("Un lien pour réserver la séance suivante vous sera envoyé par email après cette session."),
    ).toBeInTheDocument();
  });

  it("goes back to the picker without booking", async () => {
    vi.spyOn(api, "book");
    const user = await goToPicker();
    await user.click(screen.getByRole("button", { name: "14:00" }));
    await user.click(screen.getByRole("button", { name: "Changer de créneau" }));
    expect(await screen.findByRole("heading", { name: "Choisissez votre créneau" })).toBeInTheDocument();
    expect(api.book).not.toHaveBeenCalled();
    expect(api.availability).toHaveBeenCalledTimes(2); // fresh slots
  });

  it.each(["slot_taken", "slot_invalid"])("returns to the picker with a notice on %s", async (code) => {
    vi.spyOn(api, "book").mockRejectedValue(new ApiError(409, "Ce créneau vient d’être réservé.", code));
    const user = await goToPicker();
    await user.click(screen.getByRole("button", { name: "14:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    expect(await screen.findByRole("heading", { name: "Choisissez votre créneau" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Ce créneau vient d’être réservé.");
    await screen.findByRole("tablist");
    expect(api.availability).toHaveBeenCalledTimes(2);
  });

  it("reloads the page when the session was booked in another tab", async () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    vi.spyOn(api, "book").mockRejectedValue(new ApiError(409, "Déjà réservée", "already_booked"));
    const user = await goToPicker();
    await user.click(screen.getByRole("button", { name: "14:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    await waitFor(() => expect(reload).toHaveBeenCalledOnce());
    vi.unstubAllGlobals();
  });

  it("shows other booking errors in place and lets the customer retry", async () => {
    const retry = deferred<ReturnType<typeof confirmed>>();
    vi.spyOn(api, "book")
      .mockRejectedValueOnce(new ApiError(502, "Le rendez-vous n’a pas pu être créé.", "calendar_write_failed"))
      .mockReturnValueOnce(retry.promise);
    const user = await goToPicker();
    await user.click(screen.getByRole("button", { name: "14:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Le rendez-vous n’a pas pu être créé.");
    const confirm = screen.getByRole("button", { name: "Confirmer le rendez-vous" });
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // cleared while retrying
    retry.resolve(confirmed({ meet_url: null, hours_remaining: 0, hours_purchased: 1 }));
    const done = await screen.findByRole("heading", { name: "Rendez-vous confirmé" });
    const card = done.closest("section")!;
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/séance suivante/)).not.toBeInTheDocument();
  });

  it("reloads everything when another booking link is opened", async () => {
    const user = await goToPicker();
    vi.mocked(api.context).mockResolvedValue(context({ customer: { name: "Marie", email: "marie@example.com" } }));
    await user.click(screen.getByRole("link", { name: "other link" }));
    await waitFor(() => expect(api.context).toHaveBeenLastCalledWith("tok999"));
    await waitFor(() => expect(api.availability).toHaveBeenLastCalledWith("tok999"));
  });
});
