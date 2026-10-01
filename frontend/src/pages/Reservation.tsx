import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type BookingContext, type BookingInfo, type Slot } from "../api";
import { Alert, Button, Card, HoursSummary, Layout, Spinner } from "../components/Layout";
import { clock, dayKey, hm, hours, longDate, sameAsParis, shortDay, tzCity } from "../format";
import { errorText, useI18n } from "../i18n";

type Step =
  | { kind: "welcome" }
  | { kind: "pick"; notice?: ApiError }
  | { kind: "confirm"; slot: Slot }
  | { kind: "done"; booking: BookingInfo; hoursPurchased: number; hoursRemaining: number };

export default function Reservation() {
  const { token = "" } = useParams();
  const { t } = useI18n();
  // Slots are shown on the visitor's own clock (Sydney, Santiago…), with Paris time alongside.
  const tz = useMemo(() => clock.timeZone(), []);
  const [ctx, setCtx] = useState<BookingContext | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [step, setStep] = useState<Step>({ kind: "welcome" });

  useEffect(() => {
    api
      .context(token)
      .then((c) => {
        setCtx(c);
        if (c.booking) {
          setStep({
            kind: "done",
            booking: c.booking,
            hoursPurchased: c.purchase.hours_purchased,
            hoursRemaining: c.purchase.hours_remaining,
          });
        }
      })
      .catch((e: ApiError) => setLoadError(e));
  }, [token]);

  if (loadError) {
    return (
      <Layout>
        <Card>
          <h1 className="text-xl font-semibold text-slate-900">{t.booking.unavailableTitle}</h1>
          <div className="mt-4">
            <Alert>{errorText(t, loadError)}</Alert>
          </div>
          <p className="mt-4 text-sm text-slate-600">{t.booking.unavailableHelp}</p>
        </Card>
      </Layout>
    );
  }
  if (!ctx) {
    return (
      <Layout>
        <Spinner label={t.booking.loading} />
      </Layout>
    );
  }

  return (
    <Layout>
      {step.kind === "welcome" && <Welcome ctx={ctx} onNext={() => setStep({ kind: "pick" })} />}
      {step.kind === "pick" && (
        <SlotPicker token={token} tz={tz} notice={step.notice} onPick={(slot) => setStep({ kind: "confirm", slot })} />
      )}
      {step.kind === "confirm" && (
        <Confirm
          token={token}
          tz={tz}
          ctx={ctx}
          slot={step.slot}
          onBack={() => setStep({ kind: "pick" })}
          onTaken={(err) => setStep({ kind: "pick", notice: err })}
          onDone={(b) =>
            setStep({
              kind: "done",
              booking: b,
              hoursPurchased: b.hours_purchased,
              hoursRemaining: b.hours_remaining,
            })
          }
        />
      )}
      {step.kind === "done" && (
        <Done
          ctx={ctx}
          tz={tz}
          booking={step.booking}
          hoursPurchased={step.hoursPurchased}
          hoursRemaining={step.hoursRemaining}
        />
      )}
    </Layout>
  );
}

function Welcome({ ctx, onNext }: { ctx: BookingContext; onNext: () => void }) {
  const { lang, t } = useI18n();
  const p = ctx.purchase;
  if (p.hours_remaining === 0) {
    return (
      <Card>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t.allUsed.title}</h1>
        <p className="mt-4 text-slate-600">
          {t.allUsed.body(
            <a className="text-brand-600 underline" href="https://iafluence.fr">
              iafluence.fr
            </a>,
          )}
        </p>
        <div className="mt-6">
          <HoursSummary
            rows={[
              [t.summary.purchased, hours(p.hours_purchased, lang)],
              [t.summary.remaining, hours(0, lang)],
            ]}
          />
        </div>
      </Card>
    );
  }
  // hours_booked > 0 with no upcoming booking: the previous session is over, this is the follow-up link.
  const next = p.hours_booked > 0;
  return (
    <Card>
      <p className="text-sm font-medium text-brand-600">{next ? t.welcome.nextKicker : t.welcome.kicker}</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
        {next ? t.welcome.nextTitle : t.welcome.title}
      </h1>
      <div className="mt-4 space-y-2 text-slate-600">
        {next ? (
          <p>{t.welcome.nextChoose}</p>
        ) : (
          <>
            <p>{t.welcome.received}</p>
            <p>{t.welcome.choose}</p>
            <p>{t.welcome.next}</p>
          </>
        )}
      </div>
      <div className="mt-6">
        <HoursSummary
          rows={[
            [t.summary.service, t.summary.serviceName],
            [t.summary.purchased, hours(p.hours_purchased, lang)],
            [next ? t.summary.nextSession : t.summary.firstSession, hours(1, lang)],
            [t.summary.remainingAfter, hours(p.hours_remaining - 1, lang)],
          ]}
        />
      </div>
      <Button className="mt-8 w-full sm:w-auto" onClick={onNext}>
        {t.welcome.cta}
      </Button>
    </Card>
  );
}

function SlotPicker({
  token,
  tz,
  notice,
  onPick,
}: {
  token: string;
  tz: string;
  notice?: ApiError;
  onPick: (s: Slot) => void;
}) {
  const { lang, t } = useI18n();
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [day, setDay] = useState<string | null>(null);

  const load = useCallback(() => {
    setSlots(null);
    setError(null);
    api
      .availability(token)
      .then((r) => setSlots(r.slots))
      .catch((e: ApiError) => setError(e));
  }, [token]);

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
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t.picker.title}</h1>
      <p className="mt-1 text-sm text-slate-500">{parisClock ? t.picker.parisTimes : t.picker.localTimes(tzCity(tz))}</p>

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
                      ? "bg-brand-600 text-white ring-brand-600"
                      : "bg-white text-slate-700 ring-slate-200 hover:ring-brand-600"
                  }`}
                >
                  <span className={active ? "text-brand-100" : "text-slate-500"}>{d.weekday}</span>
                  <span className="text-lg font-semibold">{d.day}</span>
                  <span className={active ? "text-brand-100" : "text-slate-500"}>{d.month}</span>
                </button>
              );
            })}
          </div>

          <h2 className="mt-6 font-medium text-slate-900">
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
                  className="rounded-xl bg-white py-3 text-sm font-semibold text-brand-700 ring-1 ring-slate-200 transition hover:bg-brand-50 hover:ring-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
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
function When({ slot, tz, suffix = "" }: { slot: Slot; tz: string; suffix?: string }) {
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

function Confirm({
  token,
  tz,
  ctx,
  slot,
  onBack,
  onTaken,
  onDone,
}: {
  token: string;
  tz: string;
  ctx: BookingContext;
  slot: Slot;
  onBack: () => void;
  onTaken: (err: ApiError) => void;
  onDone: (b: Awaited<ReturnType<typeof api.book>>) => void;
}) {
  const { lang, t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.book(token, slot.start, lang, tz));
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "slot_taken" || err.code === "slot_invalid") onTaken(err);
      else if (err.code === "already_booked") window.location.reload();
      else setError(err);
      setBusy(false);
    }
  };

  return (
    <Card>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t.confirm.title}</h1>
      <div className="mt-6 rounded-xl bg-brand-50 p-5 text-brand-900 ring-1 ring-brand-100">
        <When slot={slot} tz={tz} />
        <p className="mt-3 text-sm text-brand-700">{t.confirm.with(ctx.consultant_name)}</p>
      </div>
      <p className="mt-4 text-sm text-slate-500">{t.confirm.sendTo(<strong>{ctx.customer.email}</strong>)}</p>
      <p className="mt-2 text-sm text-slate-500">{t.policy}</p>
      {error && (
        <div className="mt-4">
          <Alert>{errorText(t, error)}</Alert>
        </div>
      )}
      <div className="mt-8 flex flex-col-reverse gap-3 sm:flex-row">
        <Button variant="secondary" onClick={onBack} disabled={busy}>
          {t.confirm.change}
        </Button>
        <Button onClick={submit} disabled={busy}>
          {busy ? t.confirm.submitting : t.confirm.submit}
        </Button>
      </div>
    </Card>
  );
}

function Done({
  ctx,
  tz,
  booking,
  hoursPurchased,
  hoursRemaining,
}: {
  ctx: BookingContext;
  tz: string;
  booking: BookingInfo;
  hoursPurchased: number;
  hoursRemaining: number;
}) {
  const { lang, t } = useI18n();
  return (
    <Card>
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-100 text-emerald-700" aria-hidden>
          ✓
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{t.done.title}</h1>
      </div>
      <div className="mt-6 rounded-xl bg-slate-50 p-5 text-slate-800">
        <When slot={booking} tz={tz} suffix={` · ${t.confirm.with(ctx.consultant_name)}`} />
        {booking.meet_url && (
          <a
            href={booking.meet_url}
            className="mt-3 inline-block break-all text-sm font-medium text-brand-600 underline"
            target="_blank"
            rel="noreferrer"
          >
            {booking.meet_url}
          </a>
        )}
      </div>
      <p className="mt-4 text-sm text-slate-600">{t.done.sent(<strong>{ctx.customer.email}</strong>)}</p>
      <div className="mt-6">
        <HoursSummary
          rows={[
            [t.summary.purchased, hours(hoursPurchased, lang)],
            [t.summary.scheduled, hours(hoursPurchased - hoursRemaining, lang)],
            [t.summary.remaining, hours(hoursRemaining, lang)],
          ]}
        />
      </div>
      <p className="mt-4 text-sm text-slate-500">{t.policy}</p>
      {hoursRemaining > 0 && <p className="mt-4 text-sm text-slate-500">{t.done.next}</p>}
    </Card>
  );
}
