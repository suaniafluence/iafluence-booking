import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type LearnerList } from "../../api";
import { Icon, SectionTitle } from "../../components/Icon";
import { Alert, Button, Spinner } from "../../components/Layout";
import { longDate } from "../../format";
import { plural, Signals, StatusBadge, when } from "./shared";

/** Every learner with their time: sessions done and left, the next one, the pace, and what needs attention. */
export function Learners() {
  const [data, setData] = useState<LearnerList | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  useEffect(() => {
    setError(null);
    api
      .learners(showHidden)
      .then(setData)
      .catch((e: ApiError) => setError(e.message));
  }, [showHidden]);

  const remove = async (customerId: number) => {
    setDeleting(customerId);
    setError(null);
    try {
      await api.deleteLearner(customerId);
      setData((current) => {
        if (!current) return current;
        const removed = current.learners.find((learner) => learner.customer_id === customerId);
        return {
          ...current,
          learners: current.learners.filter((learner) => learner.customer_id !== customerId),
          hidden_count: removed?.hidden ? Math.max(0, current.hidden_count - 1) : current.hidden_count,
        };
      });
      setConfirming(null);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <section>
      <SectionTitle icon="graduation-cap">Apprenants</SectionTitle>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {!data && !error && <Spinner label="Chargement des apprenants…" />}
      {data && (
        <>
          {data.learners.length === 0 ? (
            <p className="mt-2 text-sm text-slate-500">Aucun apprenant actif.</p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-200 rounded border border-slate-200 bg-white">
              {data.learners.map((l) => (
                <li key={l.customer_id} className={l.hidden ? "opacity-60" : ""}>
                  <div className="flex items-stretch">
                    <Link
                      to={`/consultant/apprenants/${l.customer_id}`}
                      className="grid min-w-0 flex-1 gap-2 px-5 py-4 text-sm hover:bg-slate-50 sm:grid-cols-[1.4fr_1fr_1.2fr]"
                    >
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-slate-900">{l.name}</span>
                          <StatusBadge status={l.status} />
                        </div>
                        <div className="text-slate-500">{l.company ? `${l.company} · ${l.email}` : l.email}</div>
                      </div>
                      <div className="text-slate-700">
                        {l.hours_purchased > 0 ? (
                          <>
                            <div>
                              {plural(l.sessions_done, "séance faite", "séances faites")} sur {l.hours_purchased}
                            </div>
                            <div className="font-bold text-slate-900">
                              {plural(l.sessions_to_deliver, "séance restante", "séances restantes")}
                            </div>
                            {l.pace_days !== null && (
                              <div className="text-xs text-slate-500">
                                Une séance tous les {l.pace_days} j
                                {l.projected_end && ` · fin estimée ${longDate(l.projected_end, { capitalize: false })}`}
                              </div>
                            )}
                          </>
                        ) : (
                          <div className="text-slate-500">Aucune heure achetée</div>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-slate-700">
                          {l.next_session
                            ? `Prochaine : ${when(l.next_session.start)}`
                            : l.idle_days !== null
                              ? `Inactif depuis ${plural(l.idle_days, "jour", "jours")}`
                              : "—"}
                        </div>
                        <Signals signals={l.alerts} />
                      </div>
                    </Link>
                    <button
                      type="button"
                      aria-label={`Supprimer ${l.name}`}
                      title={`Supprimer ${l.name}`}
                      className="flex w-12 shrink-0 items-center justify-center border-l border-slate-200 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-[-3px] focus-visible:outline-red-500"
                      onClick={() => setConfirming(l.customer_id)}
                    >
                      <Icon name="trash" size={18} />
                    </button>
                  </div>
                  {confirming === l.customer_id && (
                    <div className="border-t border-red-100 bg-red-50 px-5 py-4 text-sm">
                      <p className="font-bold text-red-900">Supprimer définitivement {l.name} ?</p>
                      <p className="mt-1 text-red-800">
                        Toutes ses données, séances et achats seront supprimés. Cette action est irréversible.
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          className="min-h-9 px-3 text-sm"
                          onClick={() => setConfirming(null)}
                          disabled={deleting !== null}
                        >
                          Annuler
                        </Button>
                        <button
                          type="button"
                          className="min-h-9 rounded bg-red-700 px-3 text-sm font-bold text-white hover:bg-red-800 disabled:opacity-50"
                          onClick={() => remove(l.customer_id)}
                          disabled={deleting !== null}
                        >
                          {deleting === l.customer_id ? "Suppression…" : "Confirmer la suppression"}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          {(data.hidden_count > 0 || showHidden) && (
            <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} />
              Afficher les apprenants inactifs depuis plus de {data.settings.hide_after_days} jours ({data.hidden_count})
            </label>
          )}
        </>
      )}
    </section>
  );
}
