export const TZ = "Europe/Paris";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "Jeudi 8 octobre 2026" */
export function longDate(iso: string, withYear = true): string {
  return cap(
    new Intl.DateTimeFormat("fr-FR", {
      timeZone: TZ,
      weekday: "long",
      day: "numeric",
      month: "long",
      ...(withYear ? { year: "numeric" } : {}),
    }).format(new Date(iso)),
  );
}

/** "14:00" */
export function hm(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

/** "2026-10-08" in Paris time — used to group slots by day. */
export function dayKey(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

export function shortDay(iso: string): { weekday: string; day: string; month: string } {
  const d = new Date(iso);
  const f = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, ...o }).format(d);
  return { weekday: cap(f({ weekday: "short" }).replace(".", "")), day: f({ day: "numeric" }), month: f({ month: "short" }) };
}

export function hours(n: number): string {
  const v = Number.isInteger(n) ? String(n) : n.toFixed(1).replace(".", ",");
  return `${v} h`;
}

export function euros(cents: number): string {
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(cents / 100);
}
