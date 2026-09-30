import { describe, expect, it } from "vitest";
import { dayKey, euros, hm, hours, longDate, shortDay, TZ } from "./format";

// Intl uses narrow no-break spaces in fr-FR; compare on plain spaces.
const plain = (s: string) => s.replace(/\p{Zs}/gu, " ");

describe("format", () => {
  it("always formats in Paris time", () => {
    expect(TZ).toBe("Europe/Paris");
    expect(new Date("2026-10-08T12:00:00Z").getHours()).toBe(5); // the test runner itself is in Los Angeles
    expect(hm("2026-10-08T12:00:00Z")).toBe("14:00");
    expect(hm("2026-11-02T08:05:00Z")).toBe("09:05"); // winter time
  });

  it("longDate capitalises the weekday, with or without year", () => {
    expect(longDate("2026-10-08T14:00:00+02:00")).toBe("Jeudi 8 octobre 2026");
    expect(longDate("2026-10-08T14:00:00+02:00", false)).toBe("Jeudi 8 octobre");
    // 23:30 UTC on 31 Dec is already 1 Jan in Paris.
    expect(longDate("2026-12-31T23:30:00Z")).toBe("Vendredi 1 janvier 2027");
  });

  it("dayKey groups by Paris calendar day", () => {
    expect(dayKey("2026-10-08T21:59:00Z")).toBe("2026-10-08");
    expect(dayKey("2026-10-08T22:00:00Z")).toBe("2026-10-09");
  });

  it("shortDay gives a compact day label without the abbreviation dot", () => {
    expect(shortDay("2026-10-08T14:00:00+02:00")).toEqual({ weekday: "Jeu", day: "8", month: "oct." });
    expect(shortDay("2026-10-05T09:00:00+02:00").weekday).toBe("Lun");
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

  it("euros converts cents", () => {
    expect(plain(euros(150_000))).toBe("1 500,00 €");
    expect(plain(euros(0))).toBe("0,00 €");
    expect(plain(euros(1999))).toBe("19,99 €");
  });
});
