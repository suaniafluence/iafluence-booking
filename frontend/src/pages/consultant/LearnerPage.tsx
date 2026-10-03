import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ACQUISITION_SOURCES, api, ApiError, type AcquisitionSource, type LearnerDetail } from "../../api";
import { CopyButton } from "../../components/CopyButton";
import { SectionTitle } from "../../components/Icon";
import { Alert, Button, Layout, Spinner } from "../../components/Layout";
import { field, StaffLogin } from "../../components/StaffLogin";
import { euros, hm, longDate } from "../../format";
import { CompanyPanel } from "./CompanyPanel";
import { PlanPanel } from "./PlanPanel";
import { ResearchPanel } from "./ResearchPanel";
import { plural, Signals, StatusBadge, when } from "./shared";

/** While Codex works (plan, research), the page asks again this often. */
export const POLL_MS = 4000;

const KIND_LABELS = { session: "Séance", discovery: "Appel découverte", meeting: "Réunion" } as const;

/** /consultant/apprenants/:id — everything about one learner. */
export default function LearnerPage() {
  const id = Number(useParams().id);
  const [data, setData] = useState<LearnerDetail | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .learner(id)
      .then((d) => {
        setData(d);
        setNeedsLogin(false);
        setError(null);
      })
      .catch((e: ApiError) => (e.status === 401 || e.status === 403 ? setNeedsLogin(true) : setError(e.message)));
  }, [id]);

  useEffect(load, [load]);

  const working = Boolean(data?.plan?.busy || data?.research.status === "running");
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [working, load]);

  if (needsLogin) return <StaffLogin role="consultant" onSuccess={load} />;

  return (
    <Layout wide>
      <Link to="/consultant" className="text-sm font-semibold text-brand-600">
        ← Cockpit
      </Link>
      {error && (
        <div className="mt-6">
          <Alert>{error}</Alert>
        </div>
      )}
      {!data && !error && <Spinner label="Chargement…" />}
      {data && <Detail data={data} onChange={load} />}
    </Layout>
  );
}

function Detail({ data, onChange }: { data: LearnerDetail; onChange: () => void }) {
  const { customer: c, time: t } = data;
  const done = t.hours_purchased ? Math.round((100 * t.sessions_done) / t.hours_purchased) : 0;
  return (
    <div className="mt-4 space-y-10">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[32px] font-extrabold leading-none text-slate-900">{c.name}</h1>
          <StatusBadge status={t.status} />
        </div>
        <p className="mt-2 text-sm text-slate-500">
          {c.email}
          {c.company_name && ` · ${c.company_name}`}
          {c.nda_signed_at ? " · NDA signé" : c.nda_sent_at ? " · NDA envoyé" : ""}
        </p>
      </div>

      <section>
        <SectionTitle icon="calendar-check">Temps</SectionTitle>
        <div className="mt-3 space-y-3 rounded border border-slate-200 bg-white p-5 text-sm">
          {t.hours_purchased > 0 ? (
            <>
              <div
                className="h-2 overflow-hidden rounded bg-slate-100"
                role="progressbar"
                aria-label="Séances réalisées"
                aria-valuenow={done}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div className="h-full bg-brand-600" style={{ width: `${done}%` }} />
              </div>
              <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-3">
                <div>
                  <dt className="text-slate-500">Séances</dt>
                  <dd className="font-bold text-slate-900">
                    {t.sessions_done} faite(s) sur {t.hours_purchased} · {plural(t.sessions_to_deliver, "restante", "restantes")}
                  </dd>
                </div>
                <div>
                  <dt className="text-slate-500">À réserver</dt>
                  <dd className="font-bold text-slate-900">{plural(t.hours_to_schedule, "séance", "séances")} de {t.session_duration_min} min</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Prochaine séance</dt>
                  <dd className="font-bold text-slate-900">{t.next_session ? when(t.next_session.start) : "Pas encore réservée"}</dd>
                </div>
                {t.pace_days !== null && (
                  <div>
                    <dt className="text-slate-500">Rythme</dt>
                    <dd>
                      Une séance tous les {t.pace_days} j
                      {t.projected_end && ` · fin estimée ${longDate(t.projected_end, { capitalize: false })}`}
                    </dd>
                  </div>
                )}
                {t.idle_days !== null && (
                  <div>
                    <dt className="text-slate-500">Inactivité</dt>
                    <dd>{plural(t.idle_days, "jour", "jours")} sans séance</dd>
                  </div>
                )}
              </dl>
            </>
          ) : (
            <p className="text-slate-600">Aucune heure achetée pour l’instant.</p>
          )}
          <Signals signals={t.alerts} />
        </div>
      </section>

      <PlanPanel learnerId={c.id} plan={data.plan} onChange={onChange} />
      <CompanyPanel learnerId={c.id} company={data.company} onChange={onChange} />
      <ResearchPanel learnerId={c.id} research={data.research} onChange={onChange} />
      <Acquisition id={c.id} source={c.acquisition_source} detail={c.acquisition_detail} />
      <Notes id={c.id} notes={c.notes} />
      <Timeline items={data.timeline} />
      <Purchases purchases={data.purchases} />
    </div>
  );
}

function Acquisition({ id, source, detail }: { id: number; source: AcquisitionSource | null; detail: string | null }) {
  const [value, setValue] = useState<AcquisitionSource | "">(source ?? "");
  const [text, setText] = useState(detail ?? "");
  const [state, setState] = useState<"idle" | "saved" | string>("idle");
  const save = async () => {
    if (!value) return;
    try {
      await api.updateLearner(id, { acquisition_source: value, acquisition_detail: value === "autre" ? text : "" });
      setState("saved");
    } catch (e) {
      setState((e as ApiError).message);
    }
  };
  return (
    <section>
      <SectionTitle icon="user-plus">Mode d’acquisition</SectionTitle>
      <div className="mt-3 flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-5">
        <label className="block text-sm">
          <span className="text-slate-500">Comment ce client est arrivé</span>
          <select value={value} onChange={(e) => setValue(e.target.value as AcquisitionSource)} className={field}>
            <option value="" disabled>
              Non renseigné
            </option>
            {Object.entries(ACQUISITION_SOURCES).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {value === "autre" && (
          <label className="block text-sm">
            <span className="text-slate-500">Précisez</span>
            <input value={text} maxLength={255} onChange={(e) => setText(e.target.value)} className={field} />
          </label>
        )}
        <Button variant="secondary" className="min-h-9 px-3 text-sm" onClick={save} disabled={!value}>
          Enregistrer
        </Button>
        {state === "saved" && <span className="text-sm text-slate-500">Enregistré.</span>}
        {state !== "saved" && state !== "idle" && <Alert>{state}</Alert>}
      </div>
    </section>
  );
}

function Notes({ id, notes }: { id: number; notes: string | null }) {
  const [text, setText] = useState(notes ?? "");
  const [state, setState] = useState<"idle" | "saved" | string>("idle");
  const save = async () => {
    try {
      await api.updateLearner(id, { notes: text });
      setState("saved");
    } catch (e) {
      setState((e as ApiError).message);
    }
  };
  return (
    <section>
      <SectionTitle icon="notebook-pen">Notes privées</SectionTitle>
      <div className="mt-3 space-y-2 rounded border border-slate-200 bg-white p-5">
        <label className="block text-sm">
          <span className="text-slate-500">Jamais montrées au client ; données au plan d’action, pas à la recherche web.</span>
          <textarea rows={4} value={text} maxLength={10000} onChange={(e) => setText(e.target.value)} className={field} />
        </label>
        <div className="flex items-center gap-3">
          <Button variant="secondary" className="min-h-9 px-3 text-sm" onClick={save}>
            Enregistrer les notes
          </Button>
          {state === "saved" && <span className="text-sm text-slate-500">Enregistré.</span>}
          {state !== "saved" && state !== "idle" && <Alert>{state}</Alert>}
        </div>
      </div>
    </section>
  );
}

function Timeline({ items }: { items: LearnerDetail["timeline"] }) {
  return (
    <section>
      <SectionTitle icon="history">Historique</SectionTitle>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">Aucun rendez-vous.</p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-200 rounded border border-slate-200 bg-white text-sm">
          {items.map((b) => (
            <li key={b.booking_id} className="px-5 py-3">
              <div className="flex flex-wrap justify-between gap-2">
                <span className="font-bold text-slate-900">
                  {KIND_LABELS[b.kind]}
                  {b.kind !== "discovery" && ` · ${b.label}`}
                  {b.status === "cancelled" && " (annulé)"}
                </span>
                <span className="text-slate-500">
                  {longDate(b.start)} · {hm(b.start)}
                </span>
              </div>
              {b.message && <p className="mt-1 text-slate-600">Sujet indiqué : {b.message}</p>}
              {b.report?.synthese && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-brand-600">Compte rendu</summary>
                  <ul className="mt-1 list-disc pl-5 text-slate-700">
                    {[...b.report.synthese.points_abordes, ...b.report.synthese.decisions].map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </details>
              )}
              {b.report?.erased && <p className="mt-1 text-xs text-slate-500">Compte rendu effacé (durée de conservation).</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Purchases({ purchases }: { purchases: LearnerDetail["purchases"] }) {
  if (purchases.length === 0) return null;
  return (
    <section>
      <SectionTitle icon="users">Achats</SectionTitle>
      <ul className="mt-3 divide-y divide-slate-200 rounded border border-slate-200 bg-white text-sm">
        {purchases.map((p) => (
          <li key={p.id} className={`flex flex-wrap items-center justify-between gap-2 px-5 py-3 ${p.payment_status === "paid" ? "" : "line-through"}`}>
            <span>
              <span className="font-bold">{p.product}</span> · {p.hours_remaining} h restantes sur {p.hours_purchased} ·{" "}
              {euros(p.amount_cents)}
              {p.created_at && ` · ${longDate(p.created_at, { capitalize: false })}`}
            </span>
            {p.booking_url && <CopyButton text={p.booking_url} />}
          </li>
        ))}
      </ul>
    </section>
  );
}
