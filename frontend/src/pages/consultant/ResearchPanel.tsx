import { useState } from "react";
import { api, ApiError, type LearnerDetail } from "../../api";
import { SectionTitle } from "../../components/Icon";
import { Alert, Button } from "../../components/Layout";

const CONFIDENCE = { faible: "faible", moyenne: "moyenne", elevee: "élevée" } as const;

function Items({ title, items }: { title: string; items: string[] }) {
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

/** Only http(s) links are kept by the API; they open in a new tab without sending the referrer. */
function Ext({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand-600 underline">
      {children}
    </a>
  );
}

export function ResearchPanel({ learnerId, research, onChange }: { learnerId: number; research: LearnerDetail["research"]; onChange: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const running = research.status === "running";
  const r = research.content;

  const start = async () => {
    setError(null);
    try {
      await api.startResearch(learnerId);
      onChange();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };

  return (
    <section>
      <SectionTitle icon="search">Recherche web</SectionTitle>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {research.status === "failed" && research.error && (
        <div className="mt-3">
          <Alert>{research.error}</Alert>
        </div>
      )}
      <div className="mt-3 space-y-4 rounded border border-slate-200 bg-white p-5 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-slate-600">
            Codex cherche sur le web (site, LinkedIn public, presse, avis) à partir du nom, du domaine de l’email et de
            l’entreprise. Rien de vos notes ni des transcriptions ne lui est transmis.
          </p>
          <Button variant="secondary" className="min-h-9 px-3 text-sm" onClick={start} disabled={running}>
            {r ? "Relancer la recherche" : "Lancer la recherche"}
          </Button>
        </div>
        {running && <p role="status">Recherche en cours (quelques minutes)…</p>}
        {r && (
          <div className="space-y-4">
            <p className="text-slate-800">{r.synthese}</p>
            <p className="text-xs text-slate-500">Confiance : {CONFIDENCE[r.confiance]}</p>
            <div className="flex flex-wrap gap-4">
              {r.personne.role && <span>Rôle : {r.personne.role}</span>}
              {r.personne.linkedin_url && <Ext href={r.personne.linkedin_url}>LinkedIn de la personne</Ext>}
              {r.entreprise.site_web && <Ext href={r.entreprise.site_web}>Site web</Ext>}
              {r.entreprise.linkedin_url && <Ext href={r.entreprise.linkedin_url}>LinkedIn de l’entreprise</Ext>}
            </div>
            <Items title="Activité réelle" items={r.activite_reelle} />
            <Items title="Signaux positifs" items={r.signaux_positifs} />
            <Items title="Points d’attention" items={r.points_attention} />
            <Items title="Angles IA" items={r.angles_ia} />
            <Items title="Questions à poser" items={r.questions_a_poser} />
            {r.sources.length > 0 && (
              <div>
                <h4 className="font-bold text-slate-900">Sources</h4>
                <ul className="mt-1 space-y-0.5">
                  {r.sources.map((s) => (
                    <li key={s.url}>
                      <Ext href={s.url}>{s.titre}</Ext>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
