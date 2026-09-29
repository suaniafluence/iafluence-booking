import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type AdminOverview } from "../api";
import { Alert, Button, Card, Layout, Spinner } from "../components/Layout";
import { euros, hm, hours, longDate } from "../format";

export default function Admin() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .adminOverview()
      .then((d) => {
        setData(d);
        setNeedsLogin(false);
      })
      .catch((e: ApiError) => (e.status === 401 ? setNeedsLogin(true) : setError(e.message)));
  }, []);

  useEffect(load, [load]);

  if (needsLogin) return <Login onSuccess={load} />;

  return (
    <Layout wide>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Tableau de bord</h1>
        <Button
          variant="secondary"
          onClick={() => api.adminLogout().finally(() => setNeedsLogin(true))}
        >
          Déconnexion
        </Button>
      </div>
      {error && (
        <div className="mt-6">
          <Alert>{error}</Alert>
        </div>
      )}
      {!data && !error && <Spinner label="Chargement…" />}
      {data && <Dashboard data={data} />}
    </Layout>
  );
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.adminLogin(password);
      onSuccess();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <Card className="mx-auto max-w-sm">
        <h1 className="text-xl font-semibold text-slate-900">Administration</h1>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm">
            <span className="text-slate-600">Mot de passe</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600"
              required
            />
          </label>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" className="w-full" disabled={busy || !password}>
            {busy ? "Connexion…" : "Se connecter"}
          </Button>
        </form>
      </Card>
    </Layout>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900 tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}

function Dashboard({ data }: { data: AdminOverview }) {
  const k = data.kpis;
  return (
    <div className="mt-6 space-y-8">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Kpi label="Paiements du mois" value={String(k.payments_this_month)} hint={euros(k.revenue_this_month_cents)} />
        <Kpi label="Heures vendues" value={hours(k.hours_sold)} />
        <Kpi label="Heures réalisées" value={hours(k.hours_done)} />
        <Kpi label="Heures restantes à délivrer" value={hours(k.hours_to_deliver)} />
        <Kpi label="Heures à planifier" value={hours(k.hours_to_schedule)} hint={`${hours(k.hours_booked)} réservées`} />
      </div>

      <section>
        <h2 className="text-lg font-semibold text-slate-900">Prochains rendez-vous</h2>
        {data.upcoming.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">Aucun rendez-vous à venir.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white">
            {data.upcoming.map((b) => (
              <li key={b.start} className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 text-sm">
                <div>
                  <div className="font-medium text-slate-900">{b.customer}</div>
                  <div className="text-slate-500">{b.email}</div>
                </div>
                <div className="text-right">
                  <div className="text-slate-900">{longDate(b.start)}</div>
                  <div className="text-slate-500">
                    {hm(b.start)} - {hm(b.end)}
                    {b.meet_url && (
                      <>
                        {" · "}
                        <a className="text-brand-600 underline" href={b.meet_url} target="_blank" rel="noreferrer">
                          Meet
                        </a>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-slate-900">Clients</h2>
        <div className="mt-3 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-5 py-3 font-medium">Client</th>
                <th className="px-5 py-3 font-medium">Prestation</th>
                <th className="px-5 py-3 font-medium text-right">Achetées</th>
                <th className="px-5 py-3 font-medium text-right">Réservées</th>
                <th className="px-5 py-3 font-medium text-right">Restantes</th>
                <th className="px-5 py-3 font-medium">1re session</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.clients.map((c) => (
                <tr key={c.purchase_id} className={c.payment_status === "refunded" ? "text-slate-400 line-through" : ""}>
                  <td className="px-5 py-3">
                    <div className="font-medium text-slate-900">{c.name}</div>
                    <div className="text-slate-500">{c.email}</div>
                  </td>
                  <td className="px-5 py-3">{c.product}</td>
                  <td className="px-5 py-3 text-right tabular-nums">{hours(c.hours_purchased)}</td>
                  <td className="px-5 py-3 text-right tabular-nums">{hours(c.hours_booked)}</td>
                  <td className="px-5 py-3 text-right font-semibold tabular-nums">{hours(c.hours_remaining)}</td>
                  <td className="px-5 py-3 text-slate-600">
                    {c.booking ? `${longDate(c.booking.start)} · ${hm(c.booking.start)}` : "—"}
                  </td>
                </tr>
              ))}
              {data.clients.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-6 text-center text-slate-500">
                    Aucun client pour le moment.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
