import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../../api";
import { deferred } from "../../test/fixtures";
import { CalendarPrint, defaultPeriod } from "./CalendarPrint";

const PDF = new Blob(["%PDF-"], { type: "application/pdf" });
let clicked: { href: string; download: string }[];

beforeEach(() => {
  clicked = [];
  URL.createObjectURL = vi.fn(() => "blob:calendrier");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, download: this.download });
  });
  // Thursday 1 October 2026, 14:00 in Paris.
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date("2026-10-01T12:00:00Z") });
});

afterEach(() => {
  vi.useRealTimers();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("defaultPeriod", () => {
  it("is this week and the next one, Monday to Sunday", () => {
    expect(defaultPeriod(new Date("2026-10-01T12:00:00Z"))).toEqual({ start: "2026-09-28", end: "2026-10-11" });
    expect(defaultPeriod(new Date("2026-10-05T08:00:00Z"))).toEqual({ start: "2026-10-05", end: "2026-10-18" });
    expect(defaultPeriod(new Date("2026-10-11T12:00:00Z"))).toEqual({ start: "2026-10-05", end: "2026-10-18" });
  });

  it("follows the day in Paris, not on the visitor's clock", () => {
    // Sunday 4 October, 23:30 UTC: already Monday 5 in Paris (still Sunday afternoon in Los Angeles).
    expect(defaultPeriod(new Date("2026-10-04T23:30:00Z"))).toEqual({ start: "2026-10-05", end: "2026-10-18" });
  });

  it("crosses months and years", () => {
    expect(defaultPeriod(new Date("2026-12-31T12:00:00Z"))).toEqual({ start: "2026-12-28", end: "2027-01-10" });
  });
});

describe("CalendarPrint", () => {
  it("downloads the PDF of the chosen period", async () => {
    const pdf = deferred<Blob>();
    vi.spyOn(api, "adminCalendarPdf").mockReturnValue(pdf.promise);
    render(<CalendarPrint />);
    expect(screen.getByRole("heading", { name: "Imprimer mon calendrier" })).toBeInTheDocument();
    expect(screen.getByText(/se termine par « \? » sont en pointillé \(pas encore fixés ou pas sûrs\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Du")).toHaveValue("2026-09-28");
    expect(screen.getByLabelText("Au")).toHaveValue("2026-10-11");

    fireEvent.change(screen.getByLabelText("Du"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByLabelText("Au"), { target: { value: "2026-10-25" } });
    await user().click(screen.getByRole("button", { name: "Télécharger le PDF" }));

    expect(api.adminCalendarPdf).toHaveBeenCalledWith("2026-10-05", "2026-10-25");
    expect(screen.getByRole("button", { name: "Préparation du PDF…" })).toBeDisabled();
    expect(clicked).toEqual([]);

    await act(async () => pdf.resolve(PDF));
    expect(URL.createObjectURL).toHaveBeenCalledWith(PDF);
    expect(clicked).toEqual([{ href: "blob:calendrier", download: "calendrier-2026-10-05-au-2026-10-25.pdf" }]);
    expect(screen.getByRole("button", { name: "Télécharger le PDF" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(59_000));
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:calendrier");
  });

  it("accepts a single day", async () => {
    vi.spyOn(api, "adminCalendarPdf").mockResolvedValue(PDF);
    render(<CalendarPrint />);
    fireEvent.change(screen.getByLabelText("Au"), { target: { value: "2026-09-28" } });
    await user().click(screen.getByRole("button", { name: "Télécharger le PDF" }));
    expect(api.adminCalendarPdf).toHaveBeenCalledWith("2026-09-28", "2026-09-28");
  });

  it("refuses an end before the start without asking the server", async () => {
    vi.spyOn(api, "adminCalendarPdf");
    render(<CalendarPrint />);
    fireEvent.change(screen.getByLabelText("Au"), { target: { value: "2026-09-27" } });
    await user().click(screen.getByRole("button", { name: "Télécharger le PDF" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "La date de fin doit être le même jour ou après la date de début.",
    );
    expect(api.adminCalendarPdf).not.toHaveBeenCalled();
  });

  it("shows the server error and lets the admin try again", async () => {
    vi.spyOn(api, "adminCalendarPdf").mockRejectedValueOnce(
      new ApiError(502, "Un agenda Google ne répond pas. Réessayez dans un instant."),
    );
    render(<CalendarPrint />);
    await user().click(screen.getByRole("button", { name: "Télécharger le PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Un agenda Google ne répond pas.");
    expect(clicked).toEqual([]);

    vi.mocked(api.adminCalendarPdf).mockResolvedValue(PDF);
    await user().click(screen.getByRole("button", { name: "Télécharger le PDF" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(clicked).toHaveLength(1);
  });
});
