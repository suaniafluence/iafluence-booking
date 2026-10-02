import { useState, type FormEvent } from "react";
import { api, ApiError, type Meeting } from "../../api";
import { Alert, Button } from "../../components/Layout";
import { hm, longDate } from "../../format";
import { LANG_NAMES, LANGS, type Lang } from "../../i18n";

/** « Autres réunions » : summarize, on demand, a meeting booked outside the site and recorded by Fireflies. */
export function OtherMeetings({ onCreated }: { onCreated: (message: string) => void }) {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  // On demand only: each listing is one request on the Fireflies quota.
  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setMeetings((await api.adminMeetings()).meetings);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setLoading(false);
    }
  };

  const created = (m: Meeting, reportId: number, name: string) => {
    setMeetings((list) => list!.map((x) => (x.transcript_id === m.transcript_id ? { ...x, report_id: reportId } : x)));
    setOpen(null);
    onCreated(`Compte rendu demandé pour ${name} : le brouillon Gmail sera prêt dans quelques minutes.`);
  };

  return (
    <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
      <h3 className="font-bold text-slate-900">Autres réunions</h3>
      <p className="mt-1 text-sm text-slate-500">
        Une réunion prise en dehors du site (invitation Google Agenda, appel…) et enregistrée par Fireflies : choisissez-la
        pour en faire le compte rendu. L’email est toujours préparé en brouillon, à relire avant l’envoi.
      </p>
      <Button variant="secondary" className="mt-3" onClick={load} disabled={loading}>
        {loading ? "Chargement…" : meetings ? "Actualiser" : "Voir les réunions des 7 derniers jours"}
      </Button>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {meetings && meetings.length === 0 && (
        <p className="mt-3 text-sm text-slate-500">Aucun enregistrement Fireflies ces 7 derniers jours.</p>
      )}
      {meetings && meetings.length > 0 && (
        <ul aria-label="Réunions Fireflies" className="mt-3 divide-y divide-slate-100">
          {meetings.map((m) => (
            <li key={m.transcript_id} className="py-3 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-bold text-slate-900">{m.title ?? "Réunion sans titre"}</div>
                  <div className="text-slate-500">
                    {longDate(m.start)} · {hm(m.start)} - {hm(m.end)}
                  </div>
                  {m.participants.length > 0 && <div className="text-xs text-slate-500">{m.participants.join(", ")}</div>}
                </div>
                {m.report_id !== null ? (
                  <span className="rounded-sm bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
                    Compte rendu déjà demandé
                  </span>
                ) : (
                  open !== m.transcript_id && (
                    <button
                      type="button"
                      className="font-medium text-brand-600 underline"
                      aria-label={`Faire le compte rendu de ${m.title ?? "la réunion"}`}
                      onClick={() => setOpen(m.transcript_id)}
                    >
                      Faire le compte rendu
                    </button>
                  )
                )}
              </div>
              {open === m.transcript_id && (
                <ReportForm meeting={m} onCancel={() => setOpen(null)} onCreated={(id, name) => created(m, id, name)} />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReportForm({
  meeting,
  onCancel,
  onCreated,
}: {
  meeting: Meeting;
  onCancel: () => void;
  onCreated: (reportId: number, name: string) => void;
}) {
  const [name, setName] = useState(meeting.suggested_name ?? "");
  const [email, setEmail] = useState(meeting.suggested_email ?? "");
  const [locale, setLocale] = useState<Lang>("fr");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.adminCreateMeetingReport({
        transcript_id: meeting.transcript_id,
        title: meeting.title,
        start: meeting.start,
        end: meeting.end,
        name,
        email,
        locale,
      });
      onCreated(r.report_id, name);
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };

  const field = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900";
  const listId = `participants-${meeting.transcript_id}`;
  return (
    <form onSubmit={submit} className="mt-3 grid gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-3">
      <label className="text-slate-700">
        Nom du destinataire
        <input required value={name} onChange={(e) => setName(e.target.value)} className={field} />
      </label>
      <label className="text-slate-700">
        Email
        <input
          required
          type="email"
          list={listId}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={field}
        />
        <datalist id={listId}>
          {meeting.participants.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
      </label>
      <label className="text-slate-700">
        Langue du compte rendu
        <select value={locale} onChange={(e) => setLocale(e.target.value as Lang)} className={field}>
          {LANGS.map((l) => (
            <option key={l} value={l}>
              {LANG_NAMES[l]}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <div className="sm:col-span-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex flex-col-reverse gap-3 sm:col-span-3 sm:flex-row">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Annuler
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Envoi…" : "Lancer le résumé"}
        </Button>
      </div>
    </form>
  );
}
