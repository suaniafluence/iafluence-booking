import { useCallback, useEffect, useMemo, useState } from "react";
import type { ApiError, Slot } from "../api";
import { dayKey, hm, longDate, sameAsParis, shortDay, tzCity } from "../format";
import { errorText, useI18n } from "../i18n";
import { Alert, Button, Card, Spinner } from "./Layout";

/** Days and times to choose from, on the visitor's clock with Paris time alongside.

`loadSlots` must be stable (useCallback): it is called again whenever it changes. `subtitle` says how long the
appointment lasts; the one-hour consulting session by default. */
export function SlotPicker({
  loadSlots,
  tz,
  notice,
  onPick,
  subtitle,
}: {
  loadSlots: () => Promise<{ slots: Slot[] }>;
  tz: string;
  notice?: ApiError;
  onPick: (s: Slot) => void;
  subtitle?: { parisTimes: string; localTimes: (city: string) => string };
}) {
  const { lang, t } = useI18n();
  const texts = subtitle ?? t.picker;
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [day, setDay] = useState<string | null>(null);

  const load = useCallback(() => {
    setSlots(null);
    setError(null);
    loadSlots()
      .then((r) => setSlots(r.slots))
      .catch((e: ApiError) => setError(e));
  }, [loadSlots]);

  useEffect(load, [load]);

  // Grouped by the visitor's calendar day: 16:00 in Paris on Monday is Tuesday 01:00 in Sydney.
  const byDay = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const s of slots ?? []) {
      const k = dayKey(s.start, tz);
      map.set(k, [...(map.get(k) ?? []), s]);
    }
    return map;
  }, [slots, tz]);

  const days = [...byDay.keys()];
  const selectedDay = day && byDay.has(day) ? day : days[0];
  const parisClock = (slots ?? []).every((s) => sameAsParis(s.start, tz));

  return (
    <Card>
      <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{t.picker.title}</h1>
      <p className="mt-1 text-sm text-slate-500">{parisClock ? texts.parisTimes : texts.localTimes(tzCity(tz))}</p>

      {notice && (
        <div className="mt-5">
          <Alert>{errorText(t, notice)}</Alert>
        </div>
      )}

      {error && (
        <div className="mt-6 space-y-4">
          <Alert>{errorText(t, error)}</Alert>
          <Button variant="secondary" onClick={load}>
            {t.retry}
          </Button>
        </div>
      )}

      {!error && slots === null && <Spinner label={t.picker.searching} />}

      {slots !== null && days.length === 0 && (
        <div className="mt-6">
          <Alert tone="info">{t.picker.none}</Alert>
        </div>
      )}

      {days.length > 0 && selectedDay && (
        <>
          <div className="-mx-2 mt-6 flex gap-2 overflow-x-auto px-2 pb-2" role="tablist" aria-label={t.picker.days}>
            {days.map((k) => {
              const d = shortDay(byDay.get(k)![0].start, { lang, tz });
              const active = k === selectedDay;
              return (
                <button
                  key={k}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setDay(k)}
                  className={`flex min-w-[4.5rem] flex-col items-center rounded-xl px-3 py-2 text-sm ring-1 transition ${
                    active
                      ? "bg-brand-900 text-white ring-brand-900"
                      : "bg-white text-slate-700 ring-slate-200 hover:ring-brand-600"
                  }`}
                >
                  <span className={active ? "text-brand-400" : "text-slate-500"}>{d.weekday}</span>
                  <span className="font-display text-xl font-extrabold">{d.day}</span>
                  <span className={active ? "text-brand-400" : "text-slate-500"}>{d.month}</span>
                </button>
              );
            })}
          </div>

          <h2 className="mt-6 text-lg font-extrabold text-slate-900">
            {longDate(byDay.get(selectedDay)![0].start, { withYear: false, lang, tz })}
          </h2>
          <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
            {byDay.get(selectedDay)!.map((s) => {
              const local = hm(s.start, { tz });
              const paris = sameAsParis(s.start, tz)
                ? null
                : // The Paris weekday is added when Paris is still on another day.
                  `${t.time.paris} ${dayKey(s.start) !== dayKey(s.start, tz) ? `${shortDay(s.start, { lang }).weekday} ` : ""}${hm(s.start)}`;
              return (
                <button
                  key={s.start}
                  onClick={() => onPick(s)}
                  aria-label={paris ? `${local} (${paris})` : undefined}
                  className="rounded bg-white py-3 text-sm font-bold text-brand-700 ring-1 ring-slate-300 transition hover:bg-brand-50 hover:ring-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
                >
                  {local}
                  {paris && <span className="block text-xs font-normal text-slate-500">{paris}</span>}
                </button>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

/** Date and time on the visitor's clock, plus Paris time when it reads differently. */
export function When({ slot, tz, suffix = "" }: { slot: Slot; tz: string; suffix?: string }) {
  const { lang, t } = useI18n();
  const paris = !sameAsParis(slot.start, tz);
  return (
    <>
      {paris && <p className="text-xs font-medium uppercase tracking-wide opacity-70">{t.time.localClock(tzCity(tz))}</p>}
      <p className="text-lg font-semibold">{longDate(slot.start, { lang, tz })}</p>
      <p className="mt-1">
        {hm(slot.start, { tz })} - {hm(slot.end, { tz })}
        {suffix}
      </p>
      {paris && (
        <p className="mt-2 text-sm opacity-70">
          {t.time.parisClock(
            `${longDate(slot.start, { withYear: false, capitalize: false, lang })}, ${hm(slot.start)} - ${hm(slot.end)}`,
          )}
        </p>
      )}
    </>
  );
}
