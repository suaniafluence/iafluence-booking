import { useState } from "react";
import {
  api,
  ApiError,
  reportImageUrl,
  type AdminOverview,
  type FinishedSession,
  type SessionReport,
  type Synthese,
} from "../../api";
import { Alert } from "../../components/Layout";
import { hm, longDate } from "../../format";

const SECTIONS: [keyof Synthese, string][] = [
  ["objectifs", "Objectifs"],
  ["points_abordes", "Points abordés"],
  ["decisions", "Décisions"],
  ["actions_client", "Vos actions"],
  ["prochaines_etapes", "Prochaines étapes"],
];

type Tone = "ok" | "wait" | "fail" | "off";

export function reportLabel(report: SessionReport | null): [string, Tone] {
  if (report === null) return ["Pas de compte rendu", "off"];
  switch (report.status) {
    case "waiting_transcript":
      return ["En attente de la transcription", "wait"];
    case "summarizing":
      return ["Résumé en cours", "wait"];
    case "ready":
      return ["Résumé prêt", "wait"];
    case "failed":
      return ["Échec", "fail"];
    case "drafted": {
      if (report.delivery === "failed") return ["Échec Gmail", "fail"];
      const what = report.delivery === "sent" ? "Envoyé" : "Brouillon créé";
      return [`${what} ${report.with_summary ? "avec" : "sans"} compte rendu`, report.with_summary ? "ok" : "off"];
    }
  }
}

const TONES: Record<Tone, string> = {
  ok: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  wait: "bg-amber-50 text-amber-800 ring-amber-200",
  fail: "bg-red-50 text-red-800 ring-red-200",
  off: "bg-slate-100 text-slate-600 ring-slate-200",
};

function details(r: SessionReport): string | null {
  if (r.status === "waiting_transcript") {
    const parts = [`Fireflies interrogé ${r.transcript_attempts} fois`];
    if (r.next_attempt_at) parts.push(`prochaine vérification à ${hm(r.next_attempt_at)}`);
    parts.push(`abandon à ${hm(r.waiting_until)}`);
    return parts.join(" · ");
  }
  if (r.status === "drafted" && r.drafted_at) {
    const when = `${longDate(r.drafted_at).toLowerCase()} à ${hm(r.drafted_at)}`;
    return r.delivery === "failed" ? `Tentative le ${when}` : `Préparé le ${when}`;
  }
  if (r.summary_attempts > 0 && r.status !== "summarizing") return `${r.summary_attempts} tentative(s) de résumé`;
  return null;
}

export function SessionReports({ reports, onChange }: { reports: AdminOverview["reports"]; onChange: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  // Shown at once, before the reloaded overview confirms it; dropped again if saving fails.
  const [withoutReview, setWithoutReview] = useState<boolean | null>(null);

  const act = async (s: FinishedSession, action: () => Promise<unknown>, message: string) => {
    setBusy(s.report!.id);
    setError(null);
    setDone(null);
    try {
      await action();
      setDone(message);
      onChange();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  const saveWithoutReview = async (value: boolean) => {
    setWithoutReview(value);
    setError(null);
    try {
      await api.adminSetReportSettings(value);
      onChange();
    } catch (err) {
      setError((err as ApiError).message);
      setWithoutReview(null);
    }
  };

  return (
    <section>
      <h2 className="text-lg font-semibold text-slate-900">Comptes rendus de séance</h2>
      <p className="mt-1 text-sm text-slate-500">
        {reports.enabled
          ? "À la fin de chaque séance, la transcription Fireflies est résumée par votre agent Codex, puis l’email au client est préparé en brouillon dans Gmail avec la synthèse et l’infographie."
          : "Désactivé : sans clé Fireflies ni Codex, l’email de fin de séance est préparé sans compte rendu."}
      </p>
      <label className="mt-3 flex items-start gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={withoutReview ?? reports.send_without_review}
          onChange={(e) => saveWithoutReview(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-brand-600"
        />
        <span>
          Envoyer aussi les résumés sans relecture
          <span className="block text-xs text-slate-500">
            Pour les clients en « Envoi auto ». Sinon, un email qui contient un résumé généré reste toujours en brouillon.
          </span>
        </span>
      </label>
      {done && (
        <div className="mt-3">
          <Alert tone="info">{done}</Alert>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {reports.sessions.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">Aucune séance terminée pour le moment.</p>
      ) : (
        <ul aria-label="Séances terminées" className="mt-3 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white">
          {reports.sessions.map((s) => {
            const r = s.report;
            const [label, tone] = reportLabel(r);
            const info = r && details(r);
            const idle = r !== null && (r.status === "waiting_transcript" || r.status === "failed");
            const previewable = r !== null && (r.synthese !== null || r.has_image);
            const gmailFailed = r !== null && r.status === "drafted" && r.delivery === "failed";
            return (
              <li key={s.booking_id} className="px-5 py-4 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{s.customer}</div>
                    <div className="text-slate-500">
                      {longDate(s.start)} · {hm(s.start)} · {s.product}
                    </div>
                  </div>
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${TONES[tone]}`}>{label}</span>
                </div>
                {info && <p className="mt-1 text-xs text-slate-500">{info}</p>}
                {r?.error && <p className="mt-1 text-xs text-red-700">{r.error}</p>}
                {r?.erased && (
                  <p className="mt-1 text-xs text-slate-500">Compte rendu effacé (durée de conservation écoulée).</p>
                )}
                {(previewable || idle || gmailFailed) && (
                  <div className="mt-2 flex flex-wrap gap-4">
                    {previewable && (
                      <button
                        type="button"
                        aria-expanded={open === r.id}
                        aria-label={`Aperçu du compte rendu de ${s.customer}`}
                        className="font-medium text-brand-600 underline"
                        onClick={() => setOpen(open === r.id ? null : r.id)}
                      >
                        {open === r.id ? "Masquer l’aperçu" : "Aperçu"}
                      </button>
                    )}
                    {idle && (
                      <>
                        <button
                          type="button"
                          disabled={busy === r.id}
                          className="font-medium text-brand-600 underline disabled:text-slate-400"
                          onClick={() =>
                            act(
                              s,
                              () => api.adminRetryReport(r.id),
                              r.transcript_found
                                ? `Nouveau résumé demandé pour ${s.customer}.`
                                : `Recherche Fireflies relancée pour ${s.customer} (6 h).`,
                            )
                          }
                        >
                          {r.transcript_found ? "Relancer le résumé" : "Relancer Fireflies"}
                        </button>
                        <button
                          type="button"
                          disabled={busy === r.id}
                          className="font-medium text-slate-700 underline disabled:text-slate-400"
                          onClick={() =>
                            act(
                              s,
                              () => api.adminDraftWithoutSummary(r.id),
                              `Brouillon sans résumé créé pour ${s.customer}.`,
                            )
                          }
                        >
                          Créer le brouillon sans résumé
                        </button>
                      </>
                    )}
                    {gmailFailed && (
                      <button
                        type="button"
                        disabled={busy === r.id}
                        className="font-medium text-brand-600 underline disabled:text-slate-400"
                        onClick={() =>
                          act(s, () => api.adminRetryReportEmail(r.id), `Email de ${s.customer} renvoyé à Gmail.`)
                        }
                      >
                        Recréer l’email
                      </button>
                    )}
                  </div>
                )}
                {previewable && open === r.id && <Preview session={s} report={r} />}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Preview({ session, report }: { session: FinishedSession; report: SessionReport }) {
  return (
    <div className="mt-3 grid gap-4 rounded-xl bg-slate-50 p-4 lg:grid-cols-2">
      {report.has_image && (
        <img
          src={reportImageUrl(report.id)}
          alt={`Infographie de la séance de ${session.customer}`}
          className="w-full rounded-lg border border-slate-200 bg-white"
        />
      )}
      {report.synthese && (
        <div className="space-y-3">
          {SECTIONS.filter(([key]) => report.synthese![key].length > 0).map(([key, title]) => (
            <div key={key}>
              <h3 className="font-semibold text-brand-700">{title}</h3>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">
                {report.synthese![key].map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
