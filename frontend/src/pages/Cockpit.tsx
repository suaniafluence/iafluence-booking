import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ACQUISITION_SOURCES, api, ApiError, type AcquisitionSource, type AdminOverview, type NewClient } from "../api";
import { CopyButton } from "../components/CopyButton";
import { Icon, SectionTitle, type IconName } from "../components/Icon";
import { Alert, Button, Layout, Spinner } from "../components/Layout";
import { field, StaffLogin } from "../components/StaffLogin";
import { euros, hm, hours, longDate } from "../format";
import { CalendarPrint } from "./admin/CalendarPrint";
import { NdaAgreement } from "./admin/NdaAgreement";
import { SessionReports } from "./admin/SessionReports";
import { Learners } from "./consultant/Learners";

/** /consultant: the consultant's cockpit. Configuration (Codex, Fireflies, accounts) is in /admin. */
export default function Cockpit() {
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
      .catch((e: ApiError) => (e.status === 401 || e.status === 403 ? setNeedsLogin(true) : setError(e.message)));
  }, []);

  useEffect(load, [load]);

  if (needsLogin) return <StaffLogin role="consultant" onSuccess={load} />;

  return (
    <Layout wide>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-[26px] font-extrabold leading-none text-slate-900 sm:text-[32px]">
          Cockpit <span className="hl">consultant</span>
        </h1>
        <Button
          variant="secondary"
          className="min-h-10 px-4 text-sm"
          onClick={() =>
            api
              .authLogout("consultant")
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

const TABS: { id: string; label: string; short: string; icon: IconName }[] = [
  { id: "apprenants", label: "Apprenants", short: "Apprenants", icon: "graduation-cap" },
  { id: "rendez-vous", label: "Prochains rendez-vous", short: "Rendez-vous", icon: "calendar-check" },
  { id: "calendrier", label: "Imprimer mon calendrier", short: "Calendrier", icon: "printer" },
  { id: "clients", label: "Clients", short: "Clients", icon: "users" },
  { id: "nda", label: "Accord de confidentialité (NDA)", short: "NDA", icon: "file-pen" },
  { id: "comptes-rendus", label: "Comptes rendus de séance", short: "Comptes rendus", icon: "notebook-pen" },
];
type TabId = (typeof TABS)[number]["id"];

function tabFromHash(): TabId {
  const id = window.location.hash.slice(1);
  return TABS.some((t) => t.id === id) ? id : TABS[0].id;
}

/** One tab per part of the cockpit, kept in the URL (#comptes-rendus) so a reload or a shared link reopens it.
 * Every panel stays mounted: a transcript being pasted is not lost when looking at another tab. */
function Tabs({ panels }: { panels: Record<TabId, ReactNode> }) {
  const [active, setActive] = useState<TabId>(tabFromHash);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    const onHash = () => setActive(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    // On a phone the bar scrolls sideways: keep the active tab in view.
    refs.current[active]?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [active]);

  const select = (id: TabId, focus = false) => {
    setActive(id);
    history.replaceState(null, "", `#${id}`);
    if (focus) refs.current[id]?.focus();
  };

  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === active);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    select(TABS[(next + TABS.length) % TABS.length].id, true);
  };

  return (
    <div>
      <div className="sticky top-0 z-10 -mx-4 border-b border-slate-200 bg-white/95 backdrop-blur sm:mx-0 sm:rounded-t sm:border sm:border-b-slate-200">
        <div
          role="tablist"
          aria-label="Sections du cockpit"
          onKeyDown={onKey}
          className="flex snap-x gap-1 overflow-x-auto px-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {TABS.map((t) => {
            const selected = t.id === active;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  refs.current[t.id] = el;
                }}
                type="button"
                role="tab"
                id={`tab-${t.id}`}
                aria-controls={`panel-${t.id}`}
                aria-selected={selected}
                aria-label={t.label}
                tabIndex={selected ? 0 : -1}
                onClick={() => select(t.id)}
                className={`flex min-h-12 shrink-0 snap-start items-center gap-2 whitespace-nowrap border-b-[3px] px-3 text-sm lg:gap-1.5 lg:px-2.5 font-semibold transition-colors focus:outline-none focus-visible:bg-brand-50 ${
                  selected ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-900"
                }`}
              >
                <Icon name={t.icon} size={18} />
                <span className="lg:hidden">{t.short}</span>
                <span className="hidden lg:inline">{t.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      {TABS.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`panel-${t.id}`}
          aria-labelledby={`tab-${t.id}`}
          hidden={t.id !== active}
          className="pt-6"
        >
          {panels[t.id]}
        </div>
      ))}
    </div>
  );
}

function Dashboard({ data, onChange }: { data: AdminOverview; onChange: () => void }) {
  const k = data.kpis;
  return (
    <div className="mt-6 space-y-6 sm:mt-8 sm:space-y-8">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi dark label="Paiements du mois" value={String(k.payments_this_month)} hint={euros(k.revenue_this_month_cents)} />
        <Kpi label="Heures vendues" value={hours(k.hours_sold)} />
        <Kpi label="Heures réalisées" value={hours(k.hours_done)} />
        <Kpi label="Heures restantes à délivrer" value={hours(k.hours_to_deliver)} />
        <Kpi label="Heures à planifier" value={hours(k.hours_to_schedule)} hint={`${hours(k.hours_booked)} réservées`} />
      </div>

      <Tabs
        panels={{
          apprenants: <Learners />,
          "rendez-vous": <Upcoming upcoming={data.upcoming} onChange={onChange} />,
          calendrier: <CalendarPrint />,
          clients: <Clients clients={data.clients} onChange={onChange} />,
          nda: <NdaAgreement />,
          "comptes-rendus": <SessionReports reports={data.reports} onChange={onChange} />,
        }}
      />
    </div>
  );
}

type ClientRow = AdminOverview["clients"][number];

// A table cell from `sm` up; below, a « label : value » line of the client's card.
const CELL =
  "flex items-center justify-between gap-3 py-1 before:font-normal before:text-slate-500 before:content-[attr(data-label)] sm:table-cell sm:px-5 sm:py-3 sm:before:content-none";

function Clients({ clients, onChange }: { clients: ClientRow[]; onChange: () => void }) {
  const [adding, setAdding] = useState(false);
  // The booking link of the client just added, or "" when they were added without hours.
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
            setAdded(url ?? "");
            onChange();
          }}
        />
      )}
      {added !== null && (
        <div className="mt-4">
          <Alert tone="info">
            {added ? (
              <>
                Client ajouté. Lien de réservation : <span className="break-all font-medium">{added}</span>{" "}
                <CopyButton text={added} />
              </>
            ) : (
              "Client ajouté au suivi, sans forfait : retrouvez-le dans la liste des apprenants."
            )}
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-3 rounded border border-slate-200 bg-white sm:overflow-x-auto">
        {/* On a phone each client is a card: one labelled line per column. */}
        <table className="block w-full text-left text-sm sm:table sm:min-w-full">
          <thead className="hidden bg-slate-50 text-slate-500 sm:table-header-group">
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
          <tbody className="block divide-y divide-slate-200 sm:table-row-group">
            {clients.map((c) => (
              <tr
                key={c.purchase_id}
                className={`block px-4 py-3 sm:table-row sm:p-0 ${c.payment_status === "refunded" ? "text-slate-400 line-through" : ""}`}
              >
                <td className="block pb-1 sm:table-cell sm:px-5 sm:py-3">
                  <div className="font-bold text-slate-900">{c.name}</div>
                  <div className="text-slate-500">{c.email}</div>
                </td>
                <td data-label="Prestation" className={CELL}>
                  {c.product}
                  {c.manual && (
                    <span className="ml-2 rounded-sm bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">manuel</span>
                  )}
                </td>
                <td data-label="Achetées" className={`${CELL} text-right tabular-nums`}>
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
                <td data-label="Réservées" className={`${CELL} text-right tabular-nums`}>{hours(c.hours_booked)}</td>
                <td data-label="Restantes" className={`${CELL} text-right font-bold tabular-nums`}>{hours(c.hours_remaining)}</td>
                <td data-label="Prochaine session" className={`${CELL} text-slate-600`}>
                  {c.booking ? `${longDate(c.booking.start)} · ${hm(c.booking.start)}` : "—"}
                </td>
                <td data-label="Envoi auto" className={CELL}>
                  <input
                    type="checkbox"
                    aria-label={`Envoi automatique pour ${c.name}`}
                    checked={autoSendShown[c.customer_id] ?? c.auto_send_next_link}
                    disabled={saving === c.customer_id}
                    onChange={(e) => setAutoSend(c, e.target.checked)}
                    className="h-[18px] w-[18px] accent-brand-600"
                  />
                </td>
                <td data-label="Lien" className={CELL}>{c.booking_url ? <CopyButton text={c.booking_url} /> : "—"}</td>
              </tr>
            ))}
            {clients.length === 0 && (
              <tr className="block sm:table-row">
                <td colSpan={8} className="block px-5 py-6 text-center text-slate-500 sm:table-cell">
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

function AddClient({ onCancel, onAdded }: { onCancel: () => void; onAdded: (bookingUrl: string | null) => void }) {
  const [form, setForm] = useState({
    name: "",
    email: "",
    source: "" as AcquisitionSource | "",
    detail: "",
    hours: "",
    product: "Conseil IA",
    amount: "",
    send: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: HTMLInputElement | HTMLSelectElement }) =>
    setForm({ ...form, [k]: e.target instanceof HTMLInputElement && e.target.type === "checkbox" ? e.target.checked : e.target.value });
  // Without hours the client is only added to the follow-up: no purchase, so nothing else to fill in.
  const withHours = form.hours.trim() !== "";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const client: NewClient = {
      name: form.name,
      email: form.email,
      acquisition_source: form.source as AcquisitionSource,
      acquisition_detail: form.source === "autre" ? form.detail : undefined,
      hours: withHours ? Number(form.hours) : null,
      product_name: withHours ? form.product : undefined,
      amount_cents: withHours ? Math.round(Number(form.amount.replace(",", ".") || 0) * 100) : 0,
      send_link: withHours && form.send,
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
        <span className="font-semibold text-slate-900">Mode d’acquisition</span>
        <select value={form.source} onChange={set("source")} className={field} required>
          <option value="" disabled>
            Choisir…
          </option>
          {Object.entries(ACQUISITION_SOURCES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {form.source === "autre" ? (
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Précisez</span>{" "}
          <span className="text-slate-500">(facultatif)</span>
          <input value={form.detail} onChange={set("detail")} className={field} maxLength={255} />
        </label>
      ) : (
        <div className="hidden sm:block" />
      )}
      <p className="text-sm text-slate-500 sm:col-span-2">
        Forfait payé hors du site : facultatif. Sans heures, le client est seulement ajouté au suivi, sans lien de
        réservation.
      </p>
      <label className="block text-sm">
        <span className="font-semibold text-slate-900">Heures achetées</span>{" "}
        <span className="text-slate-500">(facultatif)</span>
        <input type="number" min={1} max={100} value={form.hours} onChange={set("hours")} className={field} placeholder="Aucune" />
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
          disabled={!withHours}
        />
      </label>
      <label className="block text-sm sm:col-span-2">
        <span className="font-semibold text-slate-900">Prestation</span>
        <input value={form.product} onChange={set("product")} className={field} required={withHours} maxLength={255} disabled={!withHours} />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2">
        <input
          type="checkbox"
          checked={withHours && form.send}
          onChange={set("send")}
          disabled={!withHours}
          className="h-[18px] w-[18px] accent-brand-600"
        />
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
