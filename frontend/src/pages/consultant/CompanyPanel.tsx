import { useState, type FormEvent } from "react";
import { api, ApiError, type CompanyProfile } from "../../api";
import { SectionTitle } from "../../components/Icon";
import { Alert, Button } from "../../components/Layout";
import { field } from "../../components/StaffLogin";
import { euros } from "../../format";
import { Signals } from "./shared";

const money = (v: number | null) => (v === null ? "—" : euros(v * 100).replace(/,00\s€$/, " €"));

export function CompanyCard({ company }: { company: CompanyProfile }) {
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="font-bold text-slate-900">
          {company.nom} {company.etat === "cessee" && <span className="text-red-700">(fermée)</span>}
        </div>
        <div className="text-slate-500">
          SIREN {company.siren}
          {company.activite_code && ` · NAF ${company.activite_code}`}
          {company.date_creation && ` · créée le ${company.date_creation}`}
        </div>
        {company.adresse && <div className="text-slate-500">{company.adresse}</div>}
      </div>
      <Signals signals={company.signaux} />
      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {company.effectif && (
          <div>
            <dt className="inline text-slate-500">Effectif : </dt>
            <dd className="inline">
              {company.effectif}
              {company.effectif_annee && ` (${company.effectif_annee})`}
            </dd>
          </div>
        )}
        {company.categorie && (
          <div>
            <dt className="inline text-slate-500">Catégorie : </dt>
            <dd className="inline">{company.categorie}</dd>
          </div>
        )}
        {company.labels.length > 0 && (
          <div>
            <dt className="inline text-slate-500">Labels : </dt>
            <dd className="inline">{company.labels.join(", ")}</dd>
          </div>
        )}
      </dl>
      {company.dirigeants.length > 0 && (
        <p>
          <span className="text-slate-500">Dirigeants : </span>
          {company.dirigeants.map((d) => (d.qualite ? `${d.nom} (${d.qualite})` : d.nom)).join(", ")}
        </p>
      )}
      {company.finances.length > 0 && (
        <table className="text-left">
          <thead className="text-xs text-slate-500">
            <tr>
              <th className="pr-6">Année</th>
              <th className="pr-6">Chiffre d’affaires</th>
              <th>Résultat net</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {company.finances.map((f) => (
              <tr key={f.annee}>
                <td className="pr-6">{f.annee}</td>
                <td className="pr-6">{money(f.ca)}</td>
                <td className={f.resultat_net !== null && f.resultat_net < 0 ? "text-red-700" : ""}>{money(f.resultat_net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-xs text-slate-500">Source : annuaire officiel des entreprises (indicateurs, pas une note de solvabilité).</p>
    </div>
  );
}

export function CompanyPanel({ learnerId, company, onChange }: { learnerId: number; company: CompanyProfile | null; onChange: () => void }) {
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompanyProfile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (q?: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.companySearch(learnerId, q);
      // The suggestion fills the field only if nothing was typed meanwhile.
      if (q === undefined) setQuery((typed) => typed || r.query);
      setResults(r.results);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const open = () => {
    setSearching(true);
    setResults(null);
    run();
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(query);
  };

  const pick = async (siren: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.companyAttach(learnerId, siren);
      setSearching(false);
      onChange();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const detach = async () => {
    setError(null);
    try {
      await api.companyDetach(learnerId);
      onChange();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };

  return (
    <section>
      <SectionTitle icon="building">Entreprise</SectionTitle>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-3 space-y-4 rounded border border-slate-200 bg-white p-5">
        {company && !searching && (
          <>
            <CompanyCard company={company} />
            <div className="flex gap-2">
              <Button variant="secondary" className="min-h-9 px-3 text-sm" onClick={open}>
                Changer d’entreprise
              </Button>
              <Button variant="secondary" className="min-h-9 px-3 text-sm" onClick={detach}>
                Retirer
              </Button>
            </div>
          </>
        )}
        {!company && !searching && (
          <>
            <p className="text-sm text-slate-600">Aucune entreprise associée.</p>
            <Button variant="secondary" onClick={open}>
              Rechercher l’entreprise
            </Button>
          </>
        )}
        {searching && (
          <>
            <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
              <label className="block flex-1 text-sm">
                <span className="font-semibold text-slate-900">Nom ou SIREN</span>
                <input value={query} onChange={(e) => setQuery(e.target.value)} className={field} />
              </label>
              <Button type="submit" disabled={busy || query.trim().length < 2}>
                Rechercher
              </Button>
              <Button type="button" variant="secondary" onClick={() => setSearching(false)}>
                Annuler
              </Button>
            </form>
            {results && results.length === 0 && <p className="text-sm text-slate-500">Aucun résultat.</p>}
            {results && results.length > 0 && (
              <ul className="divide-y divide-slate-200 text-sm" aria-label="Résultats">
                {results.map((r) => (
                  <li key={r.siren} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span>
                      <span className="font-bold">{r.nom}</span>{" "}
                      <span className="text-slate-500">
                        {r.siren}
                        {r.adresse && ` · ${r.adresse}`}
                        {r.etat === "cessee" && " · fermée"}
                      </span>
                    </span>
                    <Button variant="secondary" className="min-h-9 px-3 text-sm" disabled={busy} onClick={() => pick(r.siren)}>
                      Associer
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </section>
  );
}
