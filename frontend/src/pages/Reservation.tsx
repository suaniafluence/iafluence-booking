import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type BookingContext, type BookingInfo, type Slot } from "../api";
import { Alert, Button, Card, HoursSummary, Layout, Spinner } from "../components/Layout";
import { SlotPicker, When } from "../components/SlotPicker";
import { clock, hours } from "../format";
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
  const loadSlots = useCallback(() => api.availability(token), [token]);

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
        <SlotPicker
          loadSlots={loadSlots}
          tz={tz}
          notice={step.notice}
          onPick={(slot) => setStep({ kind: "confirm", slot })}
        />
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
