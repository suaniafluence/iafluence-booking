import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError, type BookingInfo, type DiscoveryInfo, type Slot } from "../api";
import { Alert, Button, Card, Layout, Spinner } from "../components/Layout";
import { NdaBox } from "../components/NdaBox";
import { SlotPicker, When } from "../components/SlotPicker";
import { clock } from "../format";
import { errorText, useI18n } from "../i18n";

type Step =
  | { kind: "pick"; notice?: ApiError }
  | { kind: "details"; slot: Slot }
  | { kind: "done"; booking: BookingInfo; email: string; nda: boolean };

/** Free discovery call, open to anyone (linked from iafluence.fr instead of the Google appointment page). */
export default function Discovery() {
  const { t } = useI18n();
  const tz = useMemo(() => clock.timeZone(), []);
  const [info, setInfo] = useState<DiscoveryInfo | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [step, setStep] = useState<Step>({ kind: "pick" });
  const loadSlots = useCallback(() => api.discoveryAvailability(), []);

  useEffect(() => {
    api
      .discoveryInfo()
      .then(setInfo)
      .catch((e: ApiError) => setLoadError(e));
  }, []);

  if (loadError) {
    return (
      <Layout>
        <Card>
          <h1 className="text-xl font-extrabold text-slate-900">{t.discovery.kicker}</h1>
          <div className="mt-4">
            <Alert>{errorText(t, loadError)}</Alert>
          </div>
        </Card>
      </Layout>
    );
  }
  if (!info) {
    return (
      <Layout>
        <Spinner label={t.picker.searching} />
      </Layout>
    );
  }

  const min = info.duration_min;
  return (
    <Layout>
      {step.kind === "pick" && (
        <div className="space-y-6">
          <div>
            <p className="text-sm font-medium text-brand-600">{t.discovery.kicker}</p>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
              {t.discovery.title(min)}
            </h1>
            <p className="mt-3 text-slate-600">{t.discovery.intro}</p>
          </div>
          <SlotPicker
            loadSlots={loadSlots}
            tz={tz}
            notice={step.notice}
            onPick={(slot) => setStep({ kind: "details", slot })}
            subtitle={{
              parisTimes: t.discovery.parisTimes(min),
              localTimes: (city) => t.discovery.localTimes(min, city),
            }}
          />
        </div>
      )}
      {step.kind === "details" && (
        <Details
          info={info}
          tz={tz}
          slot={step.slot}
          onBack={() => setStep({ kind: "pick" })}
          onTaken={(err) => setStep({ kind: "pick", notice: err })}
          onDone={(booking, email, nda) => setStep({ kind: "done", booking, email, nda })}
        />
      )}
      {step.kind === "done" && (
        <Card>
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded bg-emerald-100 text-emerald-700" aria-hidden>
              ✓
            </span>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{t.discovery.doneTitle}</h1>
          </div>
          <div className="mt-6 rounded-xl bg-slate-50 p-5 text-slate-800">
            <When slot={step.booking} tz={tz} suffix={` · ${t.discovery.with(info.consultant_name)}`} />
            {step.booking.meet_url && (
              <a
                href={step.booking.meet_url}
                className="mt-3 inline-block break-all text-sm font-medium text-brand-600 underline"
                target="_blank"
                rel="noreferrer"
              >
                {step.booking.meet_url}
              </a>
            )}
          </div>
          <p className="mt-4 text-sm text-slate-600">{t.done.sent(<strong>{step.email}</strong>)}</p>
          {step.nda && <p className="mt-2 text-sm text-slate-600">{t.nda.sent}</p>}
          <p className="mt-2 text-sm text-slate-500">{t.discovery.reschedule}</p>
        </Card>
      )}
    </Layout>
  );
}

function Details({
  info,
  tz,
  slot,
  onBack,
  onTaken,
  onDone,
}: {
  info: DiscoveryInfo;
  tz: string;
  slot: Slot;
  onBack: () => void;
  onTaken: (err: ApiError) => void;
  onDone: (booking: BookingInfo, email: string, nda: boolean) => void;
}) {
  const { lang, t } = useI18n();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [nda, setNda] = useState(false);
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const booking = await api.bookDiscovery({
        name,
        email,
        start: slot.start,
        message,
        locale: lang,
        timezone: tz,
        nda,
        website,
      });
      onDone(booking, email, nda);
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.code === "slot_taken" || apiErr.code === "slot_invalid") onTaken(apiErr);
      else setError(apiErr);
      setBusy(false);
    }
  };

  const field =
    "mt-1 w-full rounded border-[1.5px] border-slate-300 bg-white px-3.5 py-2.5 transition-colors hover:border-slate-500 text-slate-900 focus:border-brand-600 focus:outline-none focus:ring-3 focus:ring-brand-600/20";
  return (
    <Card>
      <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{t.confirm.title}</h1>
      <div className="mt-6 rounded bg-brand-50 p-5 text-brand-900">
        <When slot={slot} tz={tz} />
        <p className="mt-3 text-sm text-brand-700">{t.discovery.with(info.consultant_name)}</p>
      </div>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm font-medium text-slate-700">
          {t.discovery.name}
          <input
            required
            maxLength={255}
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={field}
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          {t.discovery.email}
          <input
            required
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={field}
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          {t.discovery.message}
          <textarea
            rows={3}
            maxLength={1000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className={field}
          />
        </label>
        {/* Honeypot: invisible to people and screen readers, filled in by bots. */}
        <div aria-hidden="true" className="absolute -left-[10000px] h-px w-px overflow-hidden">
          <label>
            Website
            <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
          </label>
        </div>
        {info.nda_available && (
          <NdaBox consultant={info.consultant_name} checked={nda} onChange={setNda} disabled={busy} />
        )}
        <p className="text-xs text-slate-500">{t.discovery.privacy}</p>
        {error && <Alert>{errorText(t, error)}</Alert>}
        <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row">
          <Button type="button" variant="secondary" onClick={onBack} disabled={busy}>
            {t.confirm.change}
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? t.discovery.submitting : t.discovery.submit}
          </Button>
        </div>
      </form>
    </Card>
  );
}
