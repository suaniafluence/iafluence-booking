import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { clock } from "../format";
import { type Lang, LangProvider } from "../i18n";
import { deferred } from "../test/fixtures";
import Discovery from "./Discovery";

const calls = [
  { start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T14:30:00+02:00" },
  { start: "2026-10-08T14:30:00+02:00", end: "2026-10-08T15:00:00+02:00" },
];
const info = { consultant_name: "Suan Tay", timezone: "Europe/Paris", duration_min: 30 };
const booked = { start: calls[1].start, end: calls[1].end, meet_url: "https://meet.google.com/xyz" };

function renderAt(lang: Lang = "fr") {
  return render(
    <MemoryRouter initialEntries={[`/${lang}/decouverte`]}>
      <LangProvider lang={lang}>
        <Routes>
          <Route path="/:lang/decouverte" element={<Discovery />} />
        </Routes>
      </LangProvider>
    </MemoryRouter>,
  );
}

async function pick(user = userEvent.setup(), time = "14:30") {
  renderAt();
  await user.click(await screen.findByRole("button", { name: time }));
  return user;
}

async function fill(user: ReturnType<typeof userEvent.setup>, message = "") {
  await user.type(screen.getByLabelText("Nom et prénom"), "Paul Prospect");
  await user.type(screen.getByLabelText("Email"), "paul@example.com");
  if (message) await user.type(screen.getByLabelText("De quoi souhaitez-vous parler ? (facultatif)"), message);
}

beforeEach(() => {
  vi.spyOn(api, "discoveryInfo").mockResolvedValue(info);
  vi.spyOn(api, "discoveryAvailability").mockResolvedValue({ slots: calls });
  vi.spyOn(api, "bookDiscovery").mockResolvedValue(booked);
  vi.spyOn(clock, "timeZone").mockReturnValue("Europe/Paris");
});

describe("Discovery", () => {
  it("shows a spinner, then the 30-minute slots", async () => {
    const pending = deferred<typeof info>();
    vi.mocked(api.discoveryInfo).mockReturnValue(pending.promise);
    renderAt();
    expect(screen.getByRole("status")).toBeInTheDocument();
    pending.resolve(info);
    expect(
      await screen.findByRole("heading", { name: "Parlons de vos projets d’IA en 30 minutes" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Appel de 30 minutes · horaires à l’heure de Paris")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^\d\d:\d\d$/ }).map((b) => b.textContent)).toEqual(["14:00", "14:30"]);
  });

  it("shows the visitor's own clock when it differs from Paris", async () => {
    vi.mocked(clock.timeZone).mockReturnValue("America/Montreal");
    renderAt("en");
    expect(
      await screen.findByText("30-minute call · times shown in Montreal time, with Paris time below"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "08:00 (Paris 14:00)" })).toBeInTheDocument();
  });

  it("books the call with the visitor's details, language and time zone", async () => {
    const user = await pick();
    expect(screen.getByText("Appel découverte avec Suan Tay")).toBeInTheDocument();
    await fill(user, "Automatiser mes devis");
    await user.click(screen.getByRole("button", { name: "Réserver l’appel" }));

    expect(api.bookDiscovery).toHaveBeenCalledWith({
      name: "Paul Prospect",
      email: "paul@example.com",
      start: calls[1].start,
      message: "Automatiser mes devis",
      locale: "fr",
      timezone: "Europe/Paris",
      website: "",
    });
    expect(await screen.findByRole("heading", { name: "Appel découverte réservé" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://meet.google.com/xyz" })).toBeInTheDocument();
    expect(screen.getByText("paul@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Répondez simplement à l’email de confirmation/)).toBeInTheDocument();
  });

  it("shows the button as busy while booking", async () => {
    const pending = deferred<typeof booked>();
    vi.mocked(api.bookDiscovery).mockReturnValue(pending.promise);
    const user = await pick();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Réserver l’appel" }));
    expect(screen.getByRole("button", { name: "Réservation…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Changer de créneau" })).toBeDisabled();
    pending.resolve(booked);
    expect(await screen.findByRole("heading", { name: "Appel découverte réservé" })).toBeInTheDocument();
  });

  it("goes back to the slots when the time was just taken", async () => {
    vi.mocked(api.bookDiscovery).mockRejectedValue(new ApiError(409, "pris", "slot_taken"));
    const user = await pick();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Réserver l’appel" }));
    expect(await screen.findByText(/Ce créneau vient d’être réservé/)).toBeInTheDocument();
    expect(api.discoveryAvailability).toHaveBeenCalledTimes(2);
  });

  it("explains other refusals and lets the visitor try again", async () => {
    vi.mocked(api.bookDiscovery).mockRejectedValueOnce(new ApiError(409, "déjà", "discovery_already_booked"));
    const user = await pick();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Réserver l’appel" }));
    expect(await screen.findByText(/Un appel découverte est déjà prévu pour cette adresse email/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Réserver l’appel" }));
    expect(await screen.findByRole("heading", { name: "Appel découverte réservé" })).toBeInTheDocument();
  });

  it("can change the slot before booking", async () => {
    const user = await pick();
    await user.click(screen.getByRole("button", { name: "Changer de créneau" }));
    expect(await screen.findByRole("button", { name: "14:00" })).toBeInTheDocument();
    expect(api.bookDiscovery).not.toHaveBeenCalled();
  });

  it("keeps the honeypot out of sight", async () => {
    await pick();
    const trap = screen.getByLabelText("Website", { selector: "input" });
    expect(trap).toHaveAttribute("tabindex", "-1");
    expect(trap.closest("[aria-hidden='true']")).not.toBeNull();
  });

  it("says when discovery calls are closed", async () => {
    vi.mocked(api.discoveryInfo).mockRejectedValue(new ApiError(404, "fermé", "discovery_closed"));
    renderAt("es");
    expect(
      await screen.findByText("Las llamadas de descubrimiento no están disponibles en este momento."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Llamada de descubrimiento gratuita" })).toBeInTheDocument();
  });
});
