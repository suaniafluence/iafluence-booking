import type { Lang } from "./i18n";

/** The consultant's time zone: slots, Google Calendar and admin pages are in Paris time. */
export const PARIS = "Europe/Paris";

const INTL_LOCALE: Record<Lang, string> = { fr: "fr-FR", en: "en-GB", es: "es-ES" };

/** The visitor's clock — an object so tests can pretend to be in Sydney or Santiago. */
export const clock = {
  timeZone(): string {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || PARIS;
    } catch {
      return PARIS;
    }
  },
};

type Where = { lang?: Lang; tz?: string };

function format(iso: string, options: Intl.DateTimeFormatOptions, { lang = "fr", tz = PARIS }: Where): string {
  return new Intl.DateTimeFormat(INTL_LOCALE[lang], { timeZone: tz, ...options }).format(new Date(iso));
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "Jeudi 8 octobre 2026" · "Thursday, 8 October 2026" · "Jueves, 8 de octubre de 2026" */
export function longDate(iso: string, { withYear = true, capitalize = true, ...where }: Where & { withYear?: boolean; capitalize?: boolean } = {}): string {
  const s = format(iso, { weekday: "long", day: "numeric", month: "long", ...(withYear ? { year: "numeric" } : {}) }, where);
  return capitalize ? cap(s) : s;
}

/** "14:00" — 24-hour clock in every language. */
export function hm(iso: string, where: Where = {}): string {
  return format(iso, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, where);
}

/** "2026-10-08" in the given time zone — used to group slots by day. */
export function dayKey(iso: string, tz = PARIS): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

export function shortDay(iso: string, where: Where = {}): { weekday: string; day: string; month: string } {
  const f = (o: Intl.DateTimeFormatOptions) => format(iso, o, where);
  return { weekday: cap(f({ weekday: "short" }).replace(".", "")), day: f({ day: "numeric" }), month: f({ month: "short" }) };
}

/** True when the visitor's clock reads like Paris at this instant (e.g. Madrid). No zone is 24 h away, so same time = same day. */
export function sameAsParis(iso: string, tz: string): boolean {
  return hm(iso, { tz }) === hm(iso);
}

/** "Australia/Sydney" -> "Sydney", "America/Argentina/Buenos_Aires" -> "Buenos Aires" */
export function tzCity(tz: string): string {
  return tz.slice(tz.lastIndexOf("/") + 1).replace(/_/g, " ");
}

export function hours(n: number, lang: Lang = "fr"): string {
  const v = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return `${lang === "en" ? v : v.replace(".", ",")} h`;
}

export function euros(cents: number): string {
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(cents / 100);
}
