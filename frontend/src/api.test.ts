import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, reportImageUrl } from "./api";

function mockFetch(status: number, body: unknown, json = true) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: json ? () => Promise.resolve(body) : () => Promise.reject(new SyntaxError("not json")),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("GET endpoints encode their parameters and send same-origin JSON requests", async () => {
    const fetch = mockFetch(200, { token: "t" });
    await expect(api.exchangeCheckout("cs_a/b?c")).resolves.toEqual({ token: "t" });
    expect(fetch).toHaveBeenCalledWith("/api/checkout/cs_a%2Fb%3Fc", {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });

    await api.context("to/k");
    expect(fetch).toHaveBeenLastCalledWith("/api/booking/to%2Fk", expect.anything());
    await api.availability("a&b=c");
    expect(fetch).toHaveBeenLastCalledWith("/api/availability?token=a%26b%3Dc", expect.anything());
    await api.adminOverview();
    expect(fetch).toHaveBeenLastCalledWith("/api/admin/overview", expect.anything());
  });

  it("POST endpoints send a JSON body", async () => {
    const fetch = mockFetch(201, { status: "confirmed" });
    await api.book("tok", "2026-10-08T14:00:00+02:00", "en", "Australia/Sydney");
    expect(fetch).toHaveBeenLastCalledWith("/api/bookings", {
      method: "POST",
      body: JSON.stringify({
        token: "tok",
        start: "2026-10-08T14:00:00+02:00",
        locale: "en",
        timezone: "Australia/Sydney",
      }),
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    await api.adminLogin("secret");
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/login",
      expect.objectContaining({ method: "POST", body: '{"password":"secret"}' }),
    );
    await api.adminLogout();
    expect(fetch).toHaveBeenLastCalledWith("/api/admin/logout", expect.objectContaining({ method: "POST" }));
    const client = { name: "C", email: "c@x.fr", hours: 2, product_name: "Conseil IA", amount_cents: 0, send_link: true };
    await api.adminAddClient(client);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/clients",
      expect.objectContaining({ method: "POST", body: JSON.stringify(client) }),
    );
    await api.adminCancelBooking(21, false);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/bookings/21/cancel",
      expect.objectContaining({ method: "POST", body: '{"notify":false}' }),
    );
    await api.adminSetHours(3, 2);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/purchases/3",
      expect.objectContaining({ method: "PATCH", body: '{"hours_purchased":2}' }),
    );
    await api.adminSetAutoSend(7, true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/customers/7",
      expect.objectContaining({ method: "PATCH", body: '{"auto_send_next_link":true}' }),
    );
  });

  it("turns API errors into ApiError with the server message and code", async () => {
    mockFetch(409, { detail: "Créneau pris", code: "slot_taken" });
    const err = await api.book("t", "s", "fr", "Europe/Paris").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
    expect(err).toMatchObject({ status: 409, message: "Créneau pris", code: "slot_taken" });
  });

  it("uses a generic message when the error detail is not a string (e.g. validation errors)", async () => {
    mockFetch(422, { detail: [{ loc: ["body"], msg: "bad" }] });
    await expect(api.book("t", "s", "fr", "Europe/Paris")).rejects.toMatchObject({
      status: 422,
      message: "Une erreur est survenue. Veuillez réessayer.",
      code: undefined,
    });
  });

  it("copes with non-JSON error pages (e.g. proxy 502)", async () => {
    mockFetch(502, null, false);
    await expect(api.context("t")).rejects.toMatchObject({ status: 502, message: "Une erreur est survenue. Veuillez réessayer." });
  });

  it("returns an empty object for a successful non-JSON response", async () => {
    mockFetch(200, null, false);
    await expect(api.adminLogout()).resolves.toEqual({});
  });

  it("reports network failures as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.context("t")).rejects.toMatchObject({
      status: 0,
      message: "Connexion impossible. Vérifiez votre connexion internet puis réessayez.",
      code: "network",
    });
  });

  it("discovery call and meeting report endpoints", async () => {
    const fetch = mockFetch(200, {});
    await api.discoveryInfo();
    expect(fetch).toHaveBeenLastCalledWith("/api/discovery", expect.anything());
    await api.discoveryAvailability();
    expect(fetch).toHaveBeenLastCalledWith("/api/discovery/availability", expect.anything());
    const call = {
      name: "Paul",
      email: "paul@example.com",
      start: "2026-10-08T14:00:00+02:00",
      message: "",
      locale: "fr",
      timezone: "Europe/Paris",
      website: "",
    };
    await api.bookDiscovery(call);
    expect(fetch).toHaveBeenLastCalledWith("/api/discovery", expect.objectContaining({ method: "POST", body: JSON.stringify(call) }));
    await api.adminMeetings();
    expect(fetch).toHaveBeenLastCalledWith("/api/admin/meetings", expect.anything());
    const meeting = {
      transcript_id: "ff",
      title: null,
      start: "2026-10-05T10:30:00+02:00",
      end: "2026-10-05T11:00:00+02:00",
      name: "Claire",
      email: "claire@exemple.fr",
      locale: "en",
    };
    await api.adminCreateMeetingReport(meeting);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/admin/meetings",
      expect.objectContaining({ method: "POST", body: JSON.stringify(meeting) }),
    );
  });

  it("downloads the printable calendar as a PDF", async () => {
    const pdf = new Blob(["%PDF-"], { type: "application/pdf" });
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(pdf) });
    vi.stubGlobal("fetch", fetch);
    await expect(api.adminCalendarPdf("2026-10-05", "2026-10-18")).resolves.toBe(pdf);
    expect(fetch).toHaveBeenCalledWith("/api/admin/calendar.pdf?start=2026-10-05&end=2026-10-18", {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });

    mockFetch(502, { detail: "Un agenda Google ne répond pas." });
    await expect(api.adminCalendarPdf("a&b", "c")).rejects.toMatchObject({
      status: 502,
      message: "Un agenda Google ne répond pas.",
    });
  });

  it("session report and Codex endpoints", async () => {
    const fetch = mockFetch(200, {});
    const last = () => fetch.mock.lastCall as [string, RequestInit];
    await api.adminRetryReport(7);
    expect(last()).toEqual(["/api/admin/reports/7/retry", expect.objectContaining({ method: "POST" })]);
    await api.adminDraftWithoutSummary(7);
    expect(last()).toEqual(["/api/admin/reports/7/draft-without-summary", expect.objectContaining({ method: "POST" })]);
    await api.adminSetReportSettings(true);
    expect(last()).toEqual([
      "/api/admin/report-settings",
      expect.objectContaining({ method: "PATCH", body: '{"send_without_review":true}' }),
    ]);
    await api.adminCodexStatus();
    expect(last()[0]).toBe("/api/admin/codex");
    expect(last()[1].method).toBeUndefined();
    await api.adminCodexLogin();
    expect(last()).toEqual(["/api/admin/codex/login", expect.objectContaining({ method: "POST" })]);
    await api.adminCodexLoginStatus(3);
    expect(last()[0]).toBe("/api/admin/codex/login/3");
    expect(last()[1].method).toBeUndefined();
    await api.adminCodexCancelLogin(3);
    expect(last()).toEqual(["/api/admin/codex/login/3/cancel", expect.objectContaining({ method: "POST" })]);
    await api.adminCodexLogout();
    expect(last()).toEqual(["/api/admin/codex/logout", expect.objectContaining({ method: "POST" })]);
    expect(reportImageUrl(12)).toBe("/api/admin/reports/12/image.png");
  });
});
