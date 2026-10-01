import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { clock } from "../format";
import { type Lang, LangProvider, MESSAGES } from "../i18n";
import { confirmed, context, deferred, slots } from "../test/fixtures";
import Reservation from "./Reservation";

const CANCELLATION_POLICY = MESSAGES.fr.policy;

function renderAt(token = "tok123", lang: Lang = "fr") {
  return render(
    <MemoryRouter initialEntries={[`/${lang}/reservation/${token}`]}>
      <Link to={`/${lang}/reservation/tok999`}>other link</Link>
      <LangProvider lang={lang}>
        <Routes>
          <Route path="/:lang/reservation/:token" element={<Reservation />} />
        </Routes>
      </LangProvider>
    </MemoryRouter>,
  );
}

/** The visitor's browser time zone. */
const visitorIn = (tz: string) => vi.spyOn(clock, "timeZone").mockReturnValue(tz);

const timeButtons = () => screen.getAllByRole("button", { name: /^\d\d:\d\d/ });

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
  visitorIn("Europe/Paris");
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
    vi.mocked(api.context).mockRejectedValue(new ApiError(404, "Ce lien de réservation est invalide ou a expiré.", "invalid_token"));
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
      .mockRejectedValueOnce(new ApiError(503, "Les disponibilités sont momentanément indisponibles.", "calendar_unavailable"))
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
    expect(screen.getByText(CANCELLATION_POLICY)).toBeInTheDocument();

    expect(screen.queryByText(/Heure de Paris/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    expect(api.book).toHaveBeenCalledWith("tok123", "2026-10-09T09:00:00+02:00", "fr", "Europe/Paris");
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
    expect(screen.getByText(CANCELLATION_POLICY)).toBeInTheDocument();
    expect(CANCELLATION_POLICY).toBe(
      "Toute séance réservée est due. Vous pouvez la déplacer gratuitement jusqu’à 24 h avant son début en répondant " +
        "à l’email de confirmation ; passé ce délai, ou en cas d’absence, l’heure est considérée comme consommée.",
    );
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

  it.each([
    ["slot_taken", "Ce créneau vient d’être réservé ou n’est plus disponible. Veuillez choisir un autre horaire."],
    ["slot_invalid", "Ce créneau n’est pas proposé à la réservation."],
  ])("returns to the picker with a notice on %s", async (code, message) => {
    vi.spyOn(api, "book").mockRejectedValue(new ApiError(409, "message serveur", code));
    const user = await goToPicker();
    await user.click(screen.getByRole("button", { name: "14:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmer le rendez-vous" }));
    expect(await screen.findByRole("heading", { name: "Choisissez votre créneau" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
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

// Fixture slots, Paris time: Thu 8 Oct 14:00 and 16:00, Fri 9 Oct 09:00.
describe("Reservation abroad", () => {
  it("Sydney, in English: own clock, own calendar days, Paris time alongside", async () => {
    visitorIn("Australia/Sydney"); // UTC+11 in October: 9 h ahead of Paris
    const book = deferred<ReturnType<typeof confirmed>>();
    vi.spyOn(api, "book").mockReturnValue(book.promise);
    const user = userEvent.setup();
    renderAt("tok123", "en");

    expect(await screen.findByRole("heading", { name: "Your AI consulting is confirmed" })).toBeInTheDocument();
    expect(summary()).toEqual({
      Service: "AI consulting",
      "Hours purchased": "5 h",
      "First session": "1 h",
      "Hours left after this session": "4 h",
    });
    await user.click(screen.getByRole("button", { name: "Choose a time" }));
    await screen.findByRole("tablist", { name: "Available days" });
    expect(screen.getByText("One-hour session · times shown in Sydney time, with Paris time below")).toBeInTheDocument();

    // Paris Thursday 16:00 is already Friday 01:00 in Sydney: it moves to Friday.
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Thu8Oct", "Fri9Oct"]);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Thursday 8 October");
    expect(timeButtons().map((b) => b.getAttribute("aria-label"))).toEqual(["23:00 (Paris 14:00)"]);
    await user.click(screen.getByRole("tab", { name: /Fri/ }));
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Friday 9 October");
    // The Paris weekday is shown when Paris is still on the previous day.
    expect(timeButtons().map((b) => b.getAttribute("aria-label"))).toEqual(["01:00 (Paris Thu 16:00)", "18:00 (Paris 09:00)"]);
    expect(timeButtons()[0]).toHaveTextContent("01:00Paris Thu 16:00");

    await user.click(screen.getByRole("button", { name: "01:00 (Paris Thu 16:00)" }));
    expect(screen.getByRole("heading", { name: "Your appointment" })).toBeInTheDocument();
    expect(screen.getByText("Sydney time")).toBeInTheDocument();
    expect(screen.getByText("Friday, 9 October 2026")).toBeInTheDocument();
    expect(screen.getByText("01:00 - 02:00")).toBeInTheDocument();
    expect(screen.getByText("Paris time: Thursday 8 October, 16:00 - 17:00")).toBeInTheDocument();
    expect(screen.getByText("AI consulting with Suan Tay")).toBeInTheDocument();
    expect(screen.getByText(/will be sent to/)).toHaveTextContent(
      "The invitation and video call link will be sent to jean@example.com.",
    );

    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));
    expect(api.book).toHaveBeenCalledWith("tok123", "2026-10-08T16:00:00+02:00", "en", "Australia/Sydney");
    expect(screen.getByRole("button", { name: "Confirming…" })).toBeDisabled();

    book.resolve(confirmed({ start: "2026-10-08T16:00:00+02:00", end: "2026-10-08T17:00:00+02:00" }));
    expect(await screen.findByRole("heading", { name: "Appointment confirmed" })).toBeInTheDocument();
    expect(screen.getByText("01:00 - 02:00 · AI consulting with Suan Tay")).toBeInTheDocument();
    expect(screen.getByText("Paris time: Thursday 8 October, 16:00 - 17:00")).toBeInTheDocument();
    expect(summary()).toEqual({ "Hours purchased": "5 h", "Hours scheduled": "1 h", "Hours left": "4 h" });
    expect(screen.getByText("After this session, you’ll receive an email with a link to book the next one.")).toBeInTheDocument();
    expect(screen.getByText(/^Every booked session is due./)).toBeInTheDocument();
  });

  it("Santiago, in Spanish: hours behind Paris", async () => {
    visitorIn("America/Santiago"); // UTC-3 in October: 5 h behind Paris
    vi.spyOn(api, "book").mockResolvedValue(confirmed());
    const user = userEvent.setup();
    renderAt("tok123", "es");
    await user.click(await screen.findByRole("button", { name: "Elegir día y hora" }));
    await screen.findByRole("tablist", { name: "Días disponibles" });
    expect(screen.getByText("Sesión de una hora · horas de Santiago, con la hora de París debajo")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Jue8oct", "Vie9oct"]);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Jueves, 8 de octubre");
    expect(timeButtons().map((b) => b.getAttribute("aria-label"))).toEqual(["09:00 (París 14:00)", "11:00 (París 16:00)"]);

    await user.click(screen.getByRole("tab", { name: /Vie/ }));
    await user.click(screen.getByRole("button", { name: "04:00 (París 09:00)" }));
    expect(screen.getByRole("heading", { name: "Su cita" })).toBeInTheDocument();
    expect(screen.getByText("Hora de Santiago")).toBeInTheDocument();
    expect(screen.getByText("Viernes, 9 de octubre de 2026")).toBeInTheDocument();
    expect(screen.getByText("Hora de París: viernes, 9 de octubre, 09:00 - 10:00")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirmar la cita" }));
    expect(await screen.findByRole("heading", { name: "Cita confirmada" })).toBeInTheDocument();
    expect(api.book).toHaveBeenCalledWith("tok123", "2026-10-09T09:00:00+02:00", "es", "America/Santiago");
    expect(summary()).toEqual({ "Horas contratadas": "5 h", "Horas programadas": "1 h", "Horas restantes": "4 h" });
  });

  it("a French customer in London sees London time first", async () => {
    visitorIn("Europe/London");
    const user = await goToPicker();
    expect(screen.getByText("Session de 1 heure · horaires à l’heure de London, heure de Paris en dessous")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "13:00 (Paris 14:00)" }));
    expect(screen.getByText("À l’heure de London")).toBeInTheDocument();
    expect(screen.getByText("Heure de Paris : jeudi 8 octobre, 14:00 - 15:00")).toBeInTheDocument();
  });

  it("Madrid reads the same clock as Paris: a single time, no Paris reminder", async () => {
    visitorIn("Europe/Madrid");
    const user = userEvent.setup();
    renderAt("tok123", "es");
    await user.click(await screen.findByRole("button", { name: "Elegir día y hora" }));
    await screen.findByRole("tablist");
    expect(screen.getByText("Sesión de una hora · horario de París")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^\d\d:\d\d$/ }).map((b) => b.textContent)).toEqual(["14:00", "16:00"]);
    await user.click(screen.getByRole("button", { name: "14:00" }));
    expect(screen.queryByText(/Hora de/)).not.toBeInTheDocument();
  });

  it("an already booked session is shown on the visitor's clock", async () => {
    visitorIn("Australia/Sydney");
    vi.mocked(api.context).mockResolvedValue(
      context({
        booking: { start: "2026-10-08T16:00:00+02:00", end: "2026-10-08T17:00:00+02:00", meet_url: null },
        purchase: { product_name: "x", hours_purchased: 1, hours_booked: 1, hours_remaining: 0 },
      }),
    );
    renderAt("tok123", "en");
    expect(await screen.findByRole("heading", { name: "Appointment confirmed" })).toBeInTheDocument();
    expect(screen.getByText("Friday, 9 October 2026")).toBeInTheDocument();
    expect(screen.getByText("Paris time: Thursday 8 October, 16:00 - 17:00")).toBeInTheDocument();
    expect(screen.queryByText(/book the next one/)).not.toBeInTheDocument();
  });

  it.each([
    ["en", "Book your next session", "Next session", "Hours left after this session"],
    ["es", "Reserve su próxima sesión", "Próxima sesión", "Horas restantes tras esta sesión"],
  ] as const)("follow-up link, translated (%s)", async (lang, heading, nextRow, remainingRow) => {
    vi.mocked(api.context).mockResolvedValue(
      context({ purchase: { product_name: "x", hours_purchased: 3, hours_booked: 1, hours_remaining: 2 } }),
    );
    renderAt("tok123", lang);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(summary()[nextRow]).toBe("1 h");
    expect(summary()[remainingRow]).toBe("1 h");
  });

  it.each([
    ["en", "You’ve used all your hours", "Thank you for your trust. To continue with more consulting hours, visit iafluence.fr."],
    ["es", "Ya ha utilizado todas sus horas", "Gracias por su confianza. Si desea continuar con nuevas horas de asesoría, visite iafluence.fr."],
  ] as const)("all hours used, translated (%s)", async (lang, heading, body) => {
    vi.mocked(api.context).mockResolvedValue(
      context({ purchase: { product_name: "x", hours_purchased: 2, hours_booked: 2, hours_remaining: 0 } }),
    );
    renderAt("tok123", lang);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === body)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "iafluence.fr" })).toHaveAttribute("href", "https://iafluence.fr");
  });

  it.each([
    ["en", "Booking link unavailable", "This booking link is invalid or has expired."],
    ["es", "Enlace de reserva no disponible", "Este enlace de reserva no es válido o ha caducado."],
  ] as const)("translates errors (%s)", async (lang, heading, message) => {
    vi.mocked(api.context).mockRejectedValue(new ApiError(404, "Ce lien de réservation est invalide ou a expiré.", "invalid_token"));
    renderAt("tok123", lang);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });
});
