import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type AdminOverview, type NewClient } from "../api";
import { CopyButton } from "../components/CopyButton";
import { SectionTitle } from "../components/Icon";
import { Alert, Button, Card, Layout, Spinner } from "../components/Layout";
import { euros, hm, hours, longDate } from "../format";
import { CalendarPrint } from "./admin/CalendarPrint";
import { CodexConnection } from "./admin/CodexConnection";
import { FirefliesConnection } from "./admin/FirefliesConnection";
import { SessionReports } from "./admin/SessionReports";

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
        <h1 className="text-[32px] font-extrabold leading-none text-slate-900">
          Tableau de <span className="hl">bord</span>
        </h1>
        <Button
          variant="secondary"
          className="min-h-10 px-4 text-sm"
          onClick={() =>
            api
              .adminLogout()
              .catch(() => {}) // back to the login form even if the request fails
              .finally(() => setNeedsLogin(true))
          }
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
      {data && <Dashboard data={data} onChange={load} />}
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
        <h1 className="text-2xl font-extrabold text-slate-900">Administration</h1>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm">
            <span className="font-semibold text-slate-900">Mot de passe</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={field}
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

function Kpi({ label, value, hint, dark = false }: { label: string; value: string; hint?: string; dark?: boolean }) {
  return (
    <div
      className={`flex flex-col gap-1 rounded border p-[18px] ${
        dark ? "border-brand-900 bg-brand-900 text-white" : "border-slate-200 bg-white text-slate-900"
      }`}
    >
      <div className={`text-[13px] ${dark ? "text-slate-300" : "text-slate-500"}`}>{label}</div>
      <div className="font-display text-[28px] font-extrabold leading-tight tabular-nums">{value}</div>
      {hint && <div className={`text-xs ${dark ? "text-slate-300" : "text-slate-500"}`}>{hint}</div>}
    </div>
  );
}

function Dashboard({ data, onChange }: { data: AdminOverview; onChange: () => void }) {
  const k = data.kpis;
  return (
    <div className="mt-8 space-y-10">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi dark label="Paiements du mois" value={String(k.payments_this_month)} hint={euros(k.revenue_this_month_cents)} />
        <Kpi label="Heures vendues" value={hours(k.hours_sold)} />
        <Kpi label="Heures réalisées" value={hours(k.hours_done)} />
        <Kpi label="Heures restantes à délivrer" value={hours(k.hours_to_deliver)} />
        <Kpi label="Heures à planifier" value={hours(k.hours_to_schedule)} hint={`${hours(k.hours_booked)} réservées`} />
      </div>

      <Upcoming upcoming={data.upcoming} onChange={onChange} />

      <CalendarPrint />

      <Clients clients={data.clients} onChange={onChange} />

      <SessionReports reports={data.reports} onChange={onChange} />

      <CodexConnection />

      <FirefliesConnection />
    </div>
  );
}

type ClientRow = AdminOverview["clients"][number];

function Clients({ clients, onChange }: { clients: ClientRow[]; onChange: () => void }) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);
  // Shown at once, before the reloaded overview confirms it; dropped again if saving fails.
  const [autoSendShown, setAutoSendShown] = useState<Record<number, boolean>>({});
  const [editing, setEditing] = useState<{ purchaseId: number; value: string } | null>(null);

  const saveHours = async (e: FormEvent) => {
    e.preventDefault();
    const { purchaseId, value } = editing!;
    setError(null);
    try {
      await api.adminSetHours(purchaseId, Number(value));
      setEditing(null);
      onChange();
    } catch (err) {
      setError((err as ApiError).message);
    }
  };

  const setAutoSend = async (c: ClientRow, autoSend: boolean) => {
    setSaving(c.customer_id);
    setError(null);
    setAutoSendShown((m) => ({ ...m, [c.customer_id]: autoSend }));
    try {
      await api.adminSetAutoSend(c.customer_id, autoSend);
      onChange();
    } catch (err) {
      setError((err as ApiError).message);
      setAutoSendShown(({ [c.customer_id]: _, ...rest }) => rest);
    } finally {
      setSaving(null);
    }
  };

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionTitle icon="users">Clients</SectionTitle>
        {!adding && (
          <Button variant="secondary" className="min-h-10 px-4 text-sm" onClick={() => setAdding(true)}>
            Ajouter un client
          </Button>
        )}
      </div>
      <p className="mt-1.5 max-w-[80ch] text-sm text-slate-500">
        À la fin de chaque session, le lien pour réserver la suivante est envoyé automatiquement si « Envoi auto » est
        coché, sinon il est préparé en brouillon dans Gmail.
      </p>
      {adding && (
        <AddClient
          onCancel={() => setAdding(false)}
          onAdded={(url) => {
            setAdding(false);
            setAdded(url);
            onChange();
          }}
        />
      )}
      {added && (
        <div className="mt-4">
          <Alert tone="info">
            Client ajouté. Lien de réservation : <span className="break-all font-medium">{added}</span>{" "}
            <CopyButton text={added} />
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-3 overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-5 py-3 font-medium">Client</th>
              <th className="px-5 py-3 font-medium">Prestation</th>
              <th className="px-5 py-3 font-medium text-right">Achetées</th>
              <th className="px-5 py-3 font-medium text-right">Réservées</th>
              <th className="px-5 py-3 font-medium text-right">Restantes</th>
              <th className="px-5 py-3 font-medium">Prochaine session</th>
              <th className="px-5 py-3 font-medium">Envoi auto</th>
              <th className="px-5 py-3 font-medium">Lien</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {clients.map((c) => (
              <tr key={c.purchase_id} className={c.payment_status === "refunded" ? "text-slate-400 line-through" : ""}>
                <td className="px-5 py-3">
                  <div className="font-bold text-slate-900">{c.name}</div>
                  <div className="text-slate-500">{c.email}</div>
                </td>
                <td className="px-5 py-3">
                  {c.product}
                  {c.manual && (
                    <span className="ml-2 rounded-sm bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">manuel</span>
                  )}
                </td>
                <td className="px-5 py-3 text-right tabular-nums">
                  {editing?.purchaseId === c.purchase_id ? (
                    <form onSubmit={saveHours} className="flex items-center justify-end gap-2">
                      <input
                        type="number"
                        aria-label={`Heures achetées par ${c.name}`}
                        min={c.hours_booked}
                        max={100}
                        value={editing.value}
                        onChange={(e) => setEditing({ purchaseId: c.purchase_id, value: e.target.value })}
                        className="w-16 rounded border-[1.5px] border-slate-300 px-2 py-1 text-right focus:border-brand-600 focus:outline-none"
                        required
                      />
                      <button type="submit" className="font-semibold text-brand-600 underline">
                        OK
                      </button>
                      <button
                        type="button"
                        aria-label="Annuler la modification"
                        className="text-slate-500 underline"
                        onClick={() => setEditing(null)}
                      >
                        ✕
                      </button>
                    </form>
                  ) : (
                    <>
                      {hours(c.hours_purchased)}
                      <button
                        type="button"
                        aria-label={`Modifier les heures de ${c.name}`}
                        className="ml-2 text-xs font-semibold text-brand-600 underline"
                        onClick={() => setEditing({ purchaseId: c.purchase_id, value: String(c.hours_purchased) })}
                      >
                        Modifier
                      </button>
                    </>
                  )}
                </td>
                <td className="px-5 py-3 text-right tabular-nums">{hours(c.hours_booked)}</td>
                <td className="px-5 py-3 text-right font-bold tabular-nums">{hours(c.hours_remaining)}</td>
                <td className="px-5 py-3 text-slate-600">
                  {c.booking ? `${longDate(c.booking.start)} · ${hm(c.booking.start)}` : "—"}
                </td>
                <td className="px-5 py-3">
                  <input
                    type="checkbox"
                    aria-label={`Envoi automatique pour ${c.name}`}
                    checked={autoSendShown[c.customer_id] ?? c.auto_send_next_link}
                    disabled={saving === c.customer_id}
                    onChange={(e) => setAutoSend(c, e.target.checked)}
                    className="h-[18px] w-[18px] accent-brand-600"
                  />
                </td>
                <td className="px-5 py-3">{c.booking_url ? <CopyButton text={c.booking_url} /> : "—"}</td>
              </tr>
            ))}
            {clients.length === 0 && (
              <tr>
                <td colSpan={8} className="px-5 py-6 text-center text-slate-500">
                  Aucun client pour le moment.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const field =
  "mt-1.5 block min-h-12 w-full rounded border-[1.5px] border-slate-300 bg-white px-3.5 py-2.5 text-base text-slate-900 transition-colors hover:border-slate-500 focus:border-brand-600 focus:outline-none focus:ring-3 focus:ring-brand-600/20";

function AddClient({ onCancel, onAdded }: { onCancel: () => void; onAdded: (bookingUrl: string) => void }) {
  const [form, setForm] = useState({ name: "", email: "", hours: "1", product: "Conseil IA", amount: "", send: true });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: HTMLInputElement }) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const client: NewClient = {
      name: form.name,
      email: form.email,
      hours: Number(form.hours),
      product_name: form.product,
      amount_cents: Math.round(Number(form.amount.replace(",", ".") || 0) * 100),
      send_link: form.send,
    };
    try {
      onAdded((await api.adminAddClient(client)).booking_url);
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mt-4 grid gap-4 rounded border border-slate-200 bg-white p-6 sm:grid-cols-2">
      <label className="block text-sm">
        <span className="font-semibold text-slate-900">Nom</span>
        <input value={form.name} onChange={set("name")} className={field} required maxLength={255} />
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-900">Email</span>
        <input type="email" value={form.email} onChange={set("email")} className={field} required />
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-900">Heures achetées</span>
        <input type="number" min={1} max={100} value={form.hours} onChange={set("hours")} className={field} required />
      </label>
      <label className="block text-sm">
        <span className="font-semibold text-slate-900">Montant payé (€)</span>
        <input
          inputMode="decimal"
          pattern="[0-9]+([.,][0-9]{1,2})?"
          placeholder="0"
          value={form.amount}
          onChange={set("amount")}
          className={field}
        />
      </label>
      <label className="block text-sm sm:col-span-2">
        <span className="font-semibold text-slate-900">Prestation</span>
        <input value={form.product} onChange={set("product")} className={field} required maxLength={255} />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
        <input type="checkbox" checked={form.send} onChange={set("send")} className="h-[18px] w-[18px] accent-brand-600" />
        Envoyer le lien de réservation par email
      </label>
      {error && (
        <div className="sm:col-span-2">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex flex-col-reverse gap-3 sm:col-span-2 sm:flex-row">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Annuler
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? "Ajout…" : "Ajouter le client"}
        </Button>
      </div>
    </form>
  );
}

type UpcomingRow = AdminOverview["upcoming"][number];

function Upcoming({ upcoming, onChange }: { upcoming: UpcomingRow[]; onChange: () => void }) {
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const open = (b: UpcomingRow) => {
    setCancelling(b.booking_id);
    setNotify(true);
    setError(null);
    setDone(null);
  };

  const confirm = async (b: UpcomingRow) => {
    setBusy(true);
    setError(null);
    try {
      const discovery = b.kind === "discovery";
      await api.adminCancelBooking(b.booking_id, notify && !discovery);
      setCancelling(null);
      setDone(
        discovery
          ? `Appel découverte de ${b.customer} annulé : Google Agenda a envoyé l’annulation.`
          : `Séance de ${b.customer} annulée : l’heure lui a été recréditée${notify ? " et son lien lui a été renvoyé" : ""}.`,
      );
      onChange();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <SectionTitle icon="calendar-check">Prochains rendez-vous</SectionTitle>
      {done && (
        <div className="mt-3">
          <Alert tone="info">{done}</Alert>
        </div>
      )}
      {upcoming.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">Aucun rendez-vous à venir.</p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-200 rounded border border-slate-200 bg-white">
          {upcoming.map((b) => (
            <li key={b.booking_id} className="px-5 py-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-bold text-slate-900">
                    {b.customer}
                    {b.kind === "discovery" && (
                      <span className="ml-2 rounded-sm bg-brand-900 px-2 py-0.5 text-xs font-semibold text-brand-400">
                        Appel découverte
                      </span>
                    )}
                  </div>
                  <div className="text-slate-500">{b.email}</div>
                </div>
                <div className="text-right">
                  <div className="text-slate-900">{longDate(b.start)}</div>
                  <div className="text-slate-500">
                    {hm(b.start)} - {hm(b.end)}
                    {b.meet_url && (
                      <>
                        {" · "}
                        <a className="font-semibold text-brand-600 underline" href={b.meet_url} target="_blank" rel="noreferrer">
                          Meet
                        </a>
                      </>
                    )}
                    {cancelling !== b.booking_id && (
                      <>
                        {" · "}
                        <button
                          type="button"
                          aria-label={`Annuler ${b.kind === "discovery" ? "l’appel découverte" : "la séance"} de ${b.customer}`}
                          className="font-semibold text-red-700 underline"
                          onClick={() => open(b)}
                        >
                          Annuler
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
              {cancelling === b.booking_id && (
                <div className="mt-3 space-y-3 rounded bg-slate-50 p-4">
                  {b.kind === "discovery" ? (
                    <p className="text-slate-700">
                      Annuler cet appel découverte ? L’événement Google Agenda est supprimé et Google prévient le prospect.
                    </p>
                  ) : (
                    <>
                      <p className="text-slate-700">
                        Annuler cette séance ? L’événement Google Agenda est supprimé et l’heure est recréditée au client.
                      </p>
                      <label className="flex items-center gap-2 text-slate-700">
                        <input
                          type="checkbox"
                          checked={notify}
                          onChange={(e) => setNotify(e.target.checked)}
                          className="h-[18px] w-[18px] accent-brand-600"
                        />
                        Envoyer au client son lien pour choisir un autre créneau
                      </label>
                    </>
                  )}
                  {error && <Alert>{error}</Alert>}
                  <div className="flex flex-col-reverse gap-3 sm:flex-row">
                    <Button variant="secondary" onClick={() => setCancelling(null)} disabled={busy}>
                      Garder la séance
                    </Button>
                    <Button onClick={() => confirm(b)} disabled={busy}>
                      {busy ? "Annulation…" : "Confirmer l’annulation"}
                    </Button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
