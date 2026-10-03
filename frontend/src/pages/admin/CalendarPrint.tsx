import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { Alert, Button } from "../../components/Layout";
import { SectionTitle } from "../../components/Icon";
import { dayKey } from "../../format";

/** "2026-10-05" moved by `n` days, on the calendar only (no clock, no DST). */
function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** This week and the next one, Monday to Sunday, in Paris. */
export function defaultPeriod(now = new Date()): { start: string; end: string } {
  const today = dayKey(now.toISOString());
  const fromMonday = (new Date(`${today}T00:00:00Z`).getUTCDay() + 6) % 7;
  const start = addDays(today, -fromMonday);
  return { start, end: addDays(start, 13) };
}

const field =
  "mt-1 block rounded border-[1.5px] border-slate-300 bg-white px-3.5 py-2.5 transition-colors hover:border-slate-500 focus:border-brand-600 focus:outline-none focus:ring-3 focus:ring-brand-600/20";

/**
 * « Imprimer mon calendrier » : every calendar over the chosen period as a very light PDF, one page per week.
 * Nothing about the events is shown: each one is « Occupé », dotted when its title ends with « ? ».
 */
export function CalendarPrint() {
  const [period, setPeriod] = useState(() => defaultPeriod());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (period.end < period.start) {
      setError("La date de fin doit être le même jour ou après la date de début.");
      return;
    }
    setBusy(true);
    try {
      const url = URL.createObjectURL(await api.adminCalendarPdf(period.start, period.end));
      const link = document.createElement("a");
      link.href = url;
      link.download = `calendrier-${period.start}-au-${period.end}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <SectionTitle icon="printer">Imprimer mon calendrier</SectionTitle>
      <p className="mt-1 text-sm text-slate-500">
        Tous vos agendas sur la période choisie, sans aucun détail : chaque rendez-vous apparaît « Occupé ». Ceux dont le
        titre se termine par « ? » sont en pointillé (pas encore fixés ou pas sûrs). PDF très clair, une page par semaine,
        avec la date du jour en haut.
      </p>
      <form
        onSubmit={submit}
        className="mt-3 flex flex-wrap items-end gap-4 rounded-2xl border border-slate-200 bg-white p-5"
      >
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Du</span>
          <input
            type="date"
            value={period.start}
            onChange={(e) => setPeriod({ ...period, start: e.target.value })}
            className={field}
            required
          />
        </label>
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Au</span>
          <input
            type="date"
            value={period.end}
            onChange={(e) => setPeriod({ ...period, end: e.target.value })}
            className={field}
            required
          />
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? "Préparation du PDF…" : "Télécharger le PDF"}
        </Button>
        {error && (
          <div className="w-full">
            <Alert>{error}</Alert>
          </div>
        )}
      </form>
    </section>
  );
}
