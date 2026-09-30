import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type BookingContext, type BookingInfo, type Slot } from "../api";
import { Alert, Button, Card, HoursSummary, Layout, Spinner } from "../components/Layout";
import { dayKey, hm, hours, longDate, shortDay } from "../format";

type Step =
  | { kind: "welcome" }
  | { kind: "pick"; notice?: string }
  | { kind: "confirm"; slot: Slot }
  | { kind: "done"; booking: BookingInfo; hoursPurchased: number; hoursRemaining: number };

export default function Reservation() {
  const { token = "" } = useParams();
  const [ctx, setCtx] = useState<BookingContext | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
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
      .catch((e: ApiError) => setLoadError(e.message));
  }, [token]);

  if (loadError) {
    return (
      <Layout>
        <Card>
          <h1 className="text-xl font-semibold text-slate-900">Lien de réservation indisponible</h1>
          <div className="mt-4">
            <Alert>{loadError}</Alert>
          </div>
          <p className="mt-4 text-sm text-slate-600">
            Vérifiez que vous utilisez bien le lien reçu par email après votre paiement. En cas de problème, répondez
            simplement à cet email.
          </p>
        </Card>
      </Layout>
    );
  }
  if (!ctx) {
    return (
      <Layout>
        <Spinner label="Chargement de votre réservation…" />
      </Layout>
    );
  }

  return (
    <Layout>
      {step.kind === "welcome" && <Welcome ctx={ctx} onNext={() => setStep({ kind: "pick" })} />}
      {step.kind === "pick" && (
        <SlotPicker token={token} notice={step.notice} onPick={(slot) => setStep({ kind: "confirm", slot })} />
      )}
      {step.kind === "confirm" && (
        <Confirm
          token={token}
          ctx={ctx}
          slot={step.slot}
          onBack={() => setStep({ kind: "pick" })}
          onTaken={(msg) => setStep({ kind: "pick", notice: msg })}
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
          booking={step.booking}
          hoursPurchased={step.hoursPurchased}
          hoursRemaining={step.hoursRemaining}
        />
      )}
    </Layout>
  );
}

function Welcome({ ctx, onNext }: { ctx: BookingContext; onNext: () => void }) {
  const p = ctx.purchase;
  if (p.hours_remaining === 0) {
    return (
      <Card>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Toutes vos heures ont été utilisées</h1>
        <p className="mt-4 text-slate-600">
          Merci pour votre confiance. Pour poursuivre l’accompagnement, répondez simplement à l’un de nos emails.
        </p>
        <div className="mt-6">
          <HoursSummary rows={[["Heures achetées", hours(p.hours_purchased)], ["Heures restantes", hours(0)]]} />
        </div>
      </Card>
    );
  }
  // hours_booked > 0 with no upcoming booking: the previous session is over, this is the follow-up link.
  const next = p.hours_booked > 0;
  return (
    <Card>
      <p className="text-sm font-medium text-brand-600">{next ? "Conseil IA" : "Paiement reçu"}</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
        {next ? "Réservez votre prochaine session" : "Votre conseil IA est confirmé"}
      </h1>
      <div className="mt-4 space-y-2 text-slate-600">
        {next ? (
          <p>Choisissez le créneau de votre prochaine session de conseil de 1 heure.</p>
        ) : (
          <>
            <p>Votre paiement a bien été reçu.</p>
            <p>Choisissez maintenant le créneau de votre première session de conseil de 1 heure.</p>
            <p>
              Si vous avez acheté plusieurs heures, un lien pour réserver la séance suivante vous sera envoyé par email
              après chaque session.
            </p>
          </>
        )}
      </div>
      <div className="mt-6">
        <HoursSummary
          rows={[
            ["Prestation", "Conseil IA"],
            ["Heures achetées", hours(p.hours_purchased)],
            [next ? "Prochaine session" : "Première session", "1 h"],
            ["Heures restantes après cette session", hours(p.hours_remaining - 1)],
          ]}
        />
      </div>
      <Button className="mt-8 w-full sm:w-auto" onClick={onNext}>
        Choisir mon créneau
      </Button>
    </Card>
  );
}

function SlotPicker({ token, notice, onPick }: { token: string; notice?: string; onPick: (s: Slot) => void }) {
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);

  const load = useCallback(() => {
    setSlots(null);
    setError(null);
    api
      .availability(token)
      .then((r) => setSlots(r.slots))
      .catch((e: ApiError) => setError(e.message));
  }, [token]);

  useEffect(load, [load]);

  const byDay = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const s of slots ?? []) {
      const k = dayKey(s.start);
      map.set(k, [...(map.get(k) ?? []), s]);
    }
    return map;
  }, [slots]);

  const days = [...byDay.keys()];
  const selectedDay = day && byDay.has(day) ? day : days[0];

  return (
    <Card>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Choisissez votre créneau</h1>
      <p className="mt-1 text-sm text-slate-500">Session de 1 heure · horaires à l’heure de Paris</p>

      {notice && (
        <div className="mt-5">
          <Alert>{notice}</Alert>
        </div>
      )}

      {error && (
        <div className="mt-6 space-y-4">
          <Alert>{error}</Alert>
          <Button variant="secondary" onClick={load}>
            Réessayer
          </Button>
        </div>
      )}

      {!error && slots === null && <Spinner label="Recherche des disponibilités…" />}

      {slots !== null && days.length === 0 && (
        <div className="mt-6">
          <Alert tone="info">
            Aucun créneau n’est disponible pour le moment. Revenez un peu plus tard ou répondez à l’email de confirmation
            pour convenir d’un horaire.
          </Alert>
        </div>
      )}

      {days.length > 0 && selectedDay && (
        <>
          <div className="-mx-2 mt-6 flex gap-2 overflow-x-auto px-2 pb-2" role="tablist" aria-label="Jours disponibles">
            {days.map((k) => {
              const d = shortDay(byDay.get(k)![0].start);
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

          <h2 className="mt-6 font-medium text-slate-900">{longDate(byDay.get(selectedDay)![0].start, false)}</h2>
          <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
            {byDay.get(selectedDay)!.map((s) => (
              <button
                key={s.start}
                onClick={() => onPick(s)}
                className="rounded-xl bg-white py-3 text-sm font-semibold text-brand-700 ring-1 ring-slate-200 transition hover:bg-brand-50 hover:ring-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
              >
                {hm(s.start)}
              </button>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function Confirm({
  token,
  ctx,
  slot,
  onBack,
  onTaken,
  onDone,
}: {
  token: string;
  ctx: BookingContext;
  slot: Slot;
  onBack: () => void;
  onTaken: (msg: string) => void;
  onDone: (b: Awaited<ReturnType<typeof api.book>>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.book(token, slot.start));
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "slot_taken" || err.code === "slot_invalid") onTaken(err.message);
      else if (err.code === "already_booked") window.location.reload();
      else setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Card>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Votre rendez-vous</h1>
      <div className="mt-6 rounded-xl bg-brand-50 p-5 ring-1 ring-brand-100">
        <p className="text-lg font-semibold text-brand-900">{longDate(slot.start)}</p>
        <p className="mt-1 text-brand-900">
          {hm(slot.start)} - {hm(slot.end)}
        </p>
        <p className="mt-3 text-sm text-brand-700">Conseil IA avec {ctx.consultant_name}</p>
      </div>
      <p className="mt-4 text-sm text-slate-500">
        L’invitation et le lien de visioconférence seront envoyés à <strong>{ctx.customer.email}</strong>.
      </p>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-8 flex flex-col-reverse gap-3 sm:flex-row">
        <Button variant="secondary" onClick={onBack} disabled={busy}>
          Changer de créneau
        </Button>
        <Button onClick={submit} disabled={busy}>
          {busy ? "Confirmation…" : "Confirmer le rendez-vous"}
        </Button>
      </div>
    </Card>
  );
}

function Done({
  ctx,
  booking,
  hoursPurchased,
  hoursRemaining,
}: {
  ctx: BookingContext;
  booking: BookingInfo;
  hoursPurchased: number;
  hoursRemaining: number;
}) {
  return (
    <Card>
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-100 text-emerald-700" aria-hidden>
          ✓
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Rendez-vous confirmé</h1>
      </div>
      <div className="mt-6 rounded-xl bg-slate-50 p-5">
        <p className="text-lg font-semibold text-slate-900">{longDate(booking.start)}</p>
        <p className="mt-1 text-slate-700">
          {hm(booking.start)} - {hm(booking.end)} · Conseil IA avec {ctx.consultant_name}
        </p>
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
      <p className="mt-4 text-sm text-slate-600">
        Une invitation calendrier et un email de confirmation ont été envoyés à <strong>{ctx.customer.email}</strong>.
      </p>
      <div className="mt-6">
        <HoursSummary
          rows={[
            ["Heures achetées", hours(hoursPurchased)],
            ["Heures planifiées", hours(hoursPurchased - hoursRemaining)],
            ["Heures restantes", hours(hoursRemaining)],
          ]}
        />
      </div>
      {hoursRemaining > 0 && (
        <p className="mt-4 text-sm text-slate-500">
          Un lien pour réserver la séance suivante vous sera envoyé par email après cette session.
        </p>
      )}
    </Card>
  );
}
