import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type ActionPlan, type PlanContent } from "../../api";
import { SectionTitle } from "../../components/Icon";
import { Alert, Button } from "../../components/Layout";
import { field } from "../../components/StaffLogin";

const EFFORT: Record<PlanContent["priorites"][number]["effort"], string> = {
  faible: "effort faible",
  moyen: "effort moyen",
  eleve: "effort élevé",
};

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="font-bold text-slate-900">{title}</h4>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="font-bold text-slate-900">{title}</h4>
      <div className="mt-1 text-slate-700">{children}</div>
    </div>
  );
}

export function PlanView({ content }: { content: PlanContent }) {
  return (
    <div className="space-y-5 text-sm">
      <p className="text-slate-700">{content.resume}</p>
      <Block title="Objectif">
        <p className="font-semibold text-slate-900">{content.objectif}</p>
      </Block>
      <List title="Diagnostic" items={content.diagnostic} />
      <Block title="Priorités">
        <ol className="list-decimal space-y-1 pl-5">
          {content.priorites.map((p) => (
            <li key={p.titre}>
              <span className="font-semibold text-slate-900">{p.titre}</span> — {p.pourquoi} · gain : {p.gain_attendu} ·{" "}
              {EFFORT[p.effort]}
            </li>
          ))}
        </ol>
      </Block>
      <Block title="Séances">
        <ol className="space-y-3">
          {content.seances.map((s) => (
            <li key={s.numero} className="rounded border border-slate-200 p-4">
              <div className="flex flex-wrap justify-between gap-2">
                <span className="font-bold text-slate-900">
                  Séance {s.numero} — {s.titre}
                </span>
                <span className="text-slate-500">{s.duree_min} min</span>
              </div>
              <p className="mt-1">{s.objectif}</p>
              <ul className="mt-2 space-y-0.5">
                {s.deroule.map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-14 shrink-0 tabular-nums text-slate-500">{step.minutes} min</span>
                    <span>{step.activite}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2">
                <span className="font-semibold">Livrable :</span> {s.livrable}
              </p>
              {s.preparation_client.length > 0 && (
                <p>
                  <span className="font-semibold">À préparer par le client :</span> {s.preparation_client.join(" ; ")}
                </p>
              )}
            </li>
          ))}
        </ol>
      </Block>
      <List title="Entre les séances" items={content.entre_les_seances} />
      <List title="Indicateurs" items={content.indicateurs} />
      <List title="Risques" items={content.risques.map((r) => `${r.risque} → ${r.parade}`)} />
      <List title="Outils" items={content.outils.map((o) => `${o.nom} : ${o.usage} (${o.cout})`)} />
      <List title="Hypothèses à vérifier" items={content.hypotheses_a_verifier} />
      <List title="Questions à poser" items={content.questions_ouvertes} />
    </div>
  );
}

export function PlanPanel({ learnerId, plan, onChange }: { learnerId: number; plan: ActionPlan | null; onChange: () => void }) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    setSending(true);
    try {
      await action();
      onChange();
      return true;
    } catch (e) {
      setError((e as ApiError).message);
      return false;
    } finally {
      setSending(false);
    }
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (await act(() => api.sendPlanMessage(learnerId, message))) setMessage("");
  };

  const busy = plan?.busy ?? false;
  return (
    <section>
      <SectionTitle icon="route">Plan d’action</SectionTitle>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {plan?.error && !busy && (
        <div className="mt-3">
          <Alert>{plan.error}</Alert>
        </div>
      )}
      <div className="mt-3 space-y-4 rounded border border-slate-200 bg-white p-5">
        {!plan && (
          <>
            <p className="text-sm text-slate-600">
              Codex prépare un plan à partir de l’appel découverte, de la fiche entreprise, de la recherche web et de vos notes,
              calé sur les séances qui restent. Il est rédigé tout seul quand un prospect achète des heures après son appel.
            </p>
            <Button onClick={() => act(() => api.generatePlan(learnerId))} disabled={sending}>
              Générer le plan
            </Button>
          </>
        )}
        {busy && (
          <p role="status" className="text-sm text-slate-600">
            Rédaction en cours par Codex (quelques minutes)…
          </p>
        )}
        {plan?.content && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500">
              <span>
                Version {plan.version}
                {plan.validated_at ? " · validée" : " · à relire"}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  className="min-h-9 px-3 text-sm"
                  disabled={busy || sending}
                  onClick={() => act(() => api.validatePlan(learnerId, !plan.validated_at))}
                >
                  {plan.validated_at ? "Retirer la validation" : "Valider le plan"}
                </Button>
                <Button
                  variant="secondary"
                  className="min-h-9 px-3 text-sm"
                  disabled={busy || sending}
                  onClick={() => act(() => api.generatePlan(learnerId))}
                >
                  Régénérer
                </Button>
              </div>
            </div>
            <PlanView content={plan.content} />
          </>
        )}
        {plan && !plan.content && !busy && (
          <Button onClick={() => act(() => api.generatePlan(learnerId))} disabled={sending}>
            Relancer la rédaction
          </Button>
        )}
      </div>

      {plan?.content && (
        <div className="mt-4 rounded border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-900">Discuter du plan avec Codex</h3>
          <ul className="mt-3 space-y-2 text-sm" aria-label="Conversation">
            {plan.messages.map((m, i) => (
              <li
                key={i}
                className={`rounded px-3 py-2 ${m.role === "consultant" ? "ml-8 bg-brand-50 text-brand-900" : "mr-8 bg-slate-50 text-slate-800"}`}
              >
                <span className="sr-only">{m.role === "consultant" ? "Vous : " : "Codex : "}</span>
                {m.content}
              </li>
            ))}
          </ul>
          <form onSubmit={send} className="mt-3 space-y-2">
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Votre demande</span>
              <textarea
                rows={3}
                value={message}
                maxLength={4000}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Ex. : le client n’a pas de budget logiciel, remplace les outils payants ; ajoute un atelier sur les avis Google."
                className={field}
              />
            </label>
            <Button type="submit" disabled={busy || sending || !message.trim()}>
              Envoyer
            </Button>
          </form>
        </div>
      )}
    </section>
  );
}
