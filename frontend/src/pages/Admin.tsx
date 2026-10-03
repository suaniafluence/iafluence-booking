import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type PlatformSettings, type StaffMe, type StaffUser } from "../api";
import { SectionTitle } from "../components/Icon";
import { Alert, Button, Layout, Spinner } from "../components/Layout";
import { field, StaffLogin } from "../components/StaffLogin";
import { CodexConnection } from "./admin/CodexConnection";
import { FirefliesConnection } from "./admin/FirefliesConnection";

/** /admin: configuration of the platform. The day-to-day work is in the consultant cockpit (/consultant). */
export default function Admin() {
  const [me, setMe] = useState<StaffMe | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .authMe("admin")
      .then((m) => {
        setMe(m);
        setNeedsLogin(false);
      })
      .catch((e: ApiError) => (e.status === 401 || e.status === 403 ? setNeedsLogin(true) : setError(e.message)));
  }, []);

  useEffect(load, [load]);

  if (needsLogin) return <StaffLogin role="admin" onSuccess={load} />;

  return (
    <Layout wide>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[32px] font-extrabold leading-none text-slate-900">
          <span className="hl">Administration</span>
        </h1>
        <div className="flex gap-2">
          <a
            href="/consultant"
            className="inline-flex min-h-10 items-center rounded border-[1.5px] border-slate-300 bg-white px-4 text-sm font-bold text-slate-900 hover:border-brand-600 hover:text-brand-600"
          >
            Cockpit consultant
          </a>
          <Button
            variant="secondary"
            className="min-h-10 px-4 text-sm"
            onClick={() =>
              api
                .authLogout("admin")
                .catch(() => {})
                .finally(() => setNeedsLogin(true))
            }
          >
            Déconnexion
          </Button>
        </div>
      </div>
      {error && (
        <div className="mt-6">
          <Alert>{error}</Alert>
        </div>
      )}
      {!me && !error && <Spinner label="Chargement…" />}
      {me && (
        <div className="mt-8 space-y-10">
          <p className="text-sm text-slate-500">
            Connecté : {me.email || "mot de passe de secours"}
          </p>
          <StaffUsers />
          <ReminderSettings />
          <CodexConnection />
          <FirefliesConnection />
        </div>
      )}
    </Layout>
  );
}

function RoleBox({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
      {label.split(" pour ")[0]}
    </label>
  );
}

export function StaffUsers() {
  const [users, setUsers] = useState<StaffUser[] | null>(null);
  const [googleEnabled, setGoogleEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [isConsultant, setIsConsultant] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .adminUsers()
      .then((d) => {
        setUsers(d.users);
        setGoogleEnabled(d.google_enabled);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const update = async (u: StaffUser, patch: Parameters<typeof api.adminUpdateUser>[1]) => {
    setError(null);
    try {
      await api.adminUpdateUser(u.id, patch);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.adminAddUser({ email, name, is_admin: isAdmin, is_consultant: isConsultant });
      setEmail("");
      setName("");
      load();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <SectionTitle icon="shield-check">Comptes et rôles</SectionTitle>
      <p className="mt-2 text-sm text-slate-500">
        Connexion avec Google : seules les adresses listées ici entrent, dans l’espace de leur rôle. Une même adresse peut être
        administrateur et consultant ; chaque espace a sa propre session.
      </p>
      {!googleEnabled && (
        <div className="mt-3">
          <Alert tone="info">
            La connexion Google n’est pas configurée (GOOGLE_SSO_CLIENT_ID / GOOGLE_SSO_CLIENT_SECRET).
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {users === null && !error && <Spinner label="Chargement…" />}
      {users && (
        <div className="mt-3 overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-5 py-3">Compte</th>
                <th className="px-5 py-3">Rôles</th>
                <th className="px-5 py-3">Google</th>
                <th className="px-5 py-3">Actif</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {users.map((u) => (
                <tr key={u.id} className={u.active ? "" : "text-slate-400"}>
                  <td className="px-5 py-3">
                    <div className="font-bold">{u.name || u.email}</div>
                    <div className="text-slate-500">{u.email}</div>
                  </td>
                  <td className="space-y-1 px-5 py-3">
                    <RoleBox label={`Administrateur pour ${u.email}`} checked={u.is_admin} onChange={(v) => update(u, { is_admin: v })} />
                    <RoleBox label={`Consultant pour ${u.email}`} checked={u.is_consultant} onChange={(v) => update(u, { is_consultant: v })} />
                  </td>
                  <td className="px-5 py-3">
                    {u.google_linked ? (
                      <button className="text-brand-600 underline" onClick={() => update(u, { unlink_google: true })}>
                        Délier le compte Google
                      </button>
                    ) : (
                      "Pas encore connecté"
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <input
                      type="checkbox"
                      aria-label={`Compte actif : ${u.email}`}
                      checked={u.active}
                      onChange={(e) => update(u, { active: e.target.checked })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form onSubmit={add} className="mt-4 grid gap-3 rounded border border-slate-200 bg-white p-5 sm:grid-cols-[1fr_1fr_auto]">
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Adresse Google</span>
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </label>
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Nom</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className={field} />
        </label>
        <div className="flex flex-col justify-end gap-2">
          <RoleBox label="Administrateur" checked={isAdmin} onChange={setIsAdmin} />
          <RoleBox label="Consultant" checked={isConsultant} onChange={setIsConsultant} />
        </div>
        <div className="sm:col-span-3">
          <Button type="submit" disabled={busy || !email}>
            {busy ? "Ajout…" : "Ajouter le compte"}
          </Button>
        </div>
      </form>
    </section>
  );
}

export function ReminderSettings() {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [after, setAfter] = useState("");
  const [hide, setHide] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const show = (s: PlatformSettings) => {
    setSettings(s);
    setAfter(String(s.reminder_after_days));
    setHide(String(s.hide_after_days));
  };

  useEffect(() => {
    api
      .adminSettings()
      .then(show)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  const save = async (patch: Parameters<typeof api.adminUpdateSettings>[0]) => {
    setError(null);
    setSaved(false);
    try {
      show(await api.adminUpdateSettings(patch));
      setSaved(true);
    } catch (e) {
      setError((e as ApiError).message);
    }
  };

  return (
    <section>
      <SectionTitle icon="sliders">Relances et inactivité</SectionTitle>
      <p className="mt-2 text-sm text-slate-500">
        Un apprenant sans séance reçoit une relance (brouillon Gmail à relire, sauf envoi automatique), puis disparaît du
        cockpit. Il réapparaît dès qu’il réserve ou rachète des heures.
      </p>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {saved && (
        <div className="mt-3">
          <Alert tone="info">Réglages enregistrés.</Alert>
        </div>
      )}
      {settings && (
        <form
          className="mt-3 space-y-4 rounded border border-slate-200 bg-white p-5"
          onSubmit={(e) => {
            e.preventDefault();
            save({ reminder_after_days: Number(after), hide_after_days: Number(hide) });
          }}
        >
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.reminder_enabled}
              onChange={(e) => save({ reminder_enabled: e.target.checked })}
            />
            Relancer les apprenants inactifs
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.reminder_auto_send}
              onChange={(e) => save({ reminder_auto_send: e.target.checked })}
            />
            Envoyer la relance directement (sans brouillon)
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Relance après (jours sans séance)</span>
              <input type="number" min={1} max={365} required value={after} onChange={(e) => setAfter(e.target.value)} className={field} />
            </label>
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Masqué du cockpit après (jours)</span>
              <input type="number" min={2} max={730} required value={hide} onChange={(e) => setHide(e.target.value)} className={field} />
            </label>
          </div>
          <Button type="submit" variant="secondary">
            Enregistrer les délais
          </Button>
        </form>
      )}
    </section>
  );
}
