import { describe, expect, it, vi } from "vitest";
import { clock, dayKey, euros, hm, hours, longDate, PARIS, sameAsParis, shortDay, tzCity } from "./format";

// Intl uses narrow no-break spaces in fr-FR; compare on plain spaces.
const plain = (s: string) => s.replace(/\p{Zs}/gu, " ");

// Thursday 8 October 2026, 16:00 in Paris (UTC+2).
const THU_16H = "2026-10-08T16:00:00+02:00";

describe("format", () => {
  it("formats in Paris time by default, whatever the machine's clock", () => {
    expect(PARIS).toBe("Europe/Paris");
    expect(new Date("2026-10-08T12:00:00Z").getHours()).toBe(5); // the test runner itself is in Los Angeles
    expect(hm("2026-10-08T12:00:00Z")).toBe("14:00");
    expect(hm("2026-11-02T08:05:00Z")).toBe("09:05"); // winter time
    expect(hm("2026-10-08T22:00:00Z")).toBe("00:00"); // 24-hour clock, midnight is 00
  });

  it("longDate capitalises the weekday, with or without year", () => {
    expect(longDate("2026-10-08T14:00:00+02:00")).toBe("Jeudi 8 octobre 2026");
    expect(longDate("2026-10-08T14:00:00+02:00", { withYear: false })).toBe("Jeudi 8 octobre");
    expect(longDate("2026-10-08T14:00:00+02:00", { withYear: false, capitalize: false })).toBe("jeudi 8 octobre");
    // 23:30 UTC on 31 Dec is already 1 Jan in Paris.
    expect(longDate("2026-12-31T23:30:00Z")).toBe("Vendredi 1 janvier 2027");
  });

  it("longDate speaks English and Spanish", () => {
    expect(longDate(THU_16H, { lang: "en" })).toBe("Thursday, 8 October 2026");
    expect(longDate(THU_16H, { lang: "en", withYear: false })).toBe("Thursday 8 October");
    expect(longDate(THU_16H, { lang: "es" })).toBe("Jueves, 8 de octubre de 2026");
    expect(longDate(THU_16H, { lang: "es", withYear: false, capitalize: false })).toBe("jueves, 8 de octubre");
  });

  it("follows the visitor's time zone, including another calendar day", () => {
    // Sydney is on summer time (UTC+11) since 4 Oct: Paris Thursday 16:00 = Friday 01:00.
    expect(longDate(THU_16H, { lang: "en", tz: "Australia/Sydney" })).toBe("Friday, 9 October 2026");
    expect(hm(THU_16H, { tz: "Australia/Sydney" })).toBe("01:00");
    expect(dayKey(THU_16H, "Australia/Sydney")).toBe("2026-10-09");
    // Santiago is on summer time (UTC-3) since 6 Sep: Paris 16:00 = 11:00.
    expect(hm(THU_16H, { tz: "America/Santiago" })).toBe("11:00");
    expect(dayKey(THU_16H, "America/Santiago")).toBe("2026-10-08");
  });

  it("handles the opposite daylight saving changes of both hemispheres", () => {
    // Paris leaves summer time on 25 Oct 2026: Sydney goes from +9 h to +10 h ahead of Paris.
    expect(hm("2026-10-23T09:00:00+02:00", { tz: "Australia/Sydney" })).toBe("18:00");
    expect(hm("2026-10-26T09:00:00+01:00", { tz: "Australia/Sydney" })).toBe("19:00");
    // Santiago: 5 h behind Paris in October, 4 h after Paris' change.
    expect(hm("2026-10-23T09:00:00+02:00", { tz: "America/Santiago" })).toBe("04:00");
    expect(hm("2026-10-26T09:00:00+01:00", { tz: "America/Santiago" })).toBe("05:00");
  });

  it("dayKey groups by Paris calendar day by default", () => {
    expect(dayKey("2026-10-08T21:59:00Z")).toBe("2026-10-08");
    expect(dayKey("2026-10-08T22:00:00Z")).toBe("2026-10-09");
  });

  it("shortDay gives a compact day label without the abbreviation dot", () => {
    expect(shortDay("2026-10-08T14:00:00+02:00")).toEqual({ weekday: "Jeu", day: "8", month: "oct." });
    expect(shortDay("2026-10-05T09:00:00+02:00").weekday).toBe("Lun");
    expect(shortDay(THU_16H, { lang: "en", tz: "Australia/Sydney" })).toEqual({ weekday: "Fri", day: "9", month: "Oct" });
    expect(shortDay(THU_16H, { lang: "es" })).toEqual({ weekday: "Jue", day: "8", month: "oct" });
  });

  it("sameAsParis compares what the clocks read, not the zone names", () => {
    expect(sameAsParis(THU_16H, PARIS)).toBe(true);
    expect(sameAsParis(THU_16H, "Europe/Madrid")).toBe(true);
    expect(sameAsParis(THU_16H, "Europe/London")).toBe(false);
    expect(sameAsParis(THU_16H, "Australia/Sydney")).toBe(false);
    expect(sameAsParis(THU_16H, "Asia/Kolkata")).toBe(false); // half-hour offset
  });

  it("tzCity keeps the last segment of the zone name", () => {
    expect(tzCity("Australia/Sydney")).toBe("Sydney");
    expect(tzCity("America/Argentina/Buenos_Aires")).toBe("Buenos Aires");
    expect(tzCity("UTC")).toBe("UTC");
  });

  it("clock reads the browser time zone, Paris if it cannot", () => {
    expect(clock.timeZone()).toBe("America/Los_Angeles");
    vi.spyOn(Intl, "DateTimeFormat").mockImplementationOnce(() => {
      throw new RangeError("no Intl");
    });
    expect(clock.timeZone()).toBe(PARIS);
  });

  it.each([
    [0, "0 h"],
    [1, "1 h"],
    [12, "12 h"],
    [1.5, "1,5 h"],
    [0.25, "0,3 h"],
    [6.5, "6,5 h"],
  ])("hours(%s) = %s", (n, expected) => {
    expect(hours(n)).toBe(expected);
  });

  it("hours uses the decimal separator of the language", () => {
    expect(hours(1.5, "en")).toBe("1.5 h");
    expect(hours(1.5, "es")).toBe("1,5 h");
    expect(hours(2, "en")).toBe("2 h");
  });

  it("euros converts cents", () => {
    expect(plain(euros(150_000))).toBe("1 500,00 €");
    expect(plain(euros(0))).toBe("0,00 €");
    expect(plain(euros(1999))).toBe("19,99 €");
  });
});
