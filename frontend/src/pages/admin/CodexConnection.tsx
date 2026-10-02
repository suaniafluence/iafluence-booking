import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type CodexLogin, type CodexStatus } from "../../api";
import { CopyButton } from "../../components/CopyButton";
import { Alert, Button } from "../../components/Layout";
import { SectionTitle } from "../../components/Icon";
import { hm } from "../../format";

/** Status check of a pending device login (the backend also asks the codex app-server). */
export const POLL_MS = 3000;

const OUTCOME: Record<Exclude<CodexLogin["status"], "PENDING" | "COMPLETED">, string> = {
  EXPIRED: "Le code a expiré avant d’être validé. Relancez la connexion.",
  DENIED: "La connexion a été refusée sur la page OpenAI.",
  CANCELLED: "Connexion annulée.",
  ERROR: "La connexion a échoué",
};

/**
 * « Connexion Codex » : device authorization (OAuth 2.0, RFC 8628) of the codex app-server with the ChatGPT plan.
 * Only the verification page and the one-time code are shown: the OAuth tokens never leave the codex container.
 */
export function CodexConnection() {
  const [status, setStatus] = useState<CodexStatus | null>(null);
  const [login, setLogin] = useState<CodexLogin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api
      .adminCodexStatus()
      .then((s) => {
        setStatus(s);
        if (s.pending_login) setLogin(s.pending_login);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const pendingId = login?.status === "PENDING" ? login.id : null;
  useEffect(() => {
    if (pendingId === null) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = () => {
      api
        .adminCodexLoginStatus(pendingId)
        .then((l) => {
          if (stopped) return;
          if (l.status === "PENDING") {
            timer = setTimeout(check, POLL_MS);
            return;
          }
          setLogin(null);
          if (l.status === "COMPLETED") {
            setNotice("Codex est connecté : les résumés utiliseront votre forfait ChatGPT.");
            load();
          } else {
            setError(l.status === "ERROR" && l.error ? `${OUTCOME.ERROR} : ${l.error}` : OUTCOME[l.status]);
          }
        })
        .catch(() => {
          // Network hiccup: keep checking.
          if (!stopped) timer = setTimeout(check, POLL_MS);
        });
    };
    timer = setTimeout(check, POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [pendingId, load]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const connect = () => run(async () => setLogin(await api.adminCodexLogin()));
  const cancel = (l: CodexLogin) =>
    run(async () => {
      await api.adminCodexCancelLogin(l.id);
      setLogin(null);
      setNotice(OUTCOME.CANCELLED);
    });
  const logout = () =>
    run(async () => {
      await api.adminCodexLogout();
      setNotice("Codex est déconnecté.");
      load();
    });

  const showConnect = status !== null && !login && CONNECTABLE.includes(status.state);

  return (
    <section>
      <SectionTitle icon="bot">Connexion Codex</SectionTitle>
      <div className="mt-3 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl space-y-1">
            <h3 className="text-base font-bold text-slate-900">Associer votre compte ChatGPT</h3>
            <p className="text-slate-500">
              Les comptes rendus sont rédigés par votre agent Codex avec votre forfait ChatGPT. Aucun mot de passe ni
              jeton ne passe par cette page : vous validez la connexion sur le site d’OpenAI avec un code à usage
              unique.
            </p>
          </div>
          {showConnect && (
            <Button onClick={connect} disabled={busy}>
              {busy ? "Connexion…" : status?.state === "expired" ? "Reconnecter Codex" : "Connecter Codex"}
            </Button>
          )}
        </div>
        {notice && <Alert tone="info">{notice}</Alert>}
        {error && <Alert>{error}</Alert>}
        {!status && !error && <p className="text-slate-500">Vérification de la connexion…</p>}
        {status && !login && <State status={status} busy={busy} onLogout={logout} onRetry={load} />}
        {login && <DeviceCode login={login} busy={busy} onCancel={() => cancel(login)} />}
      </div>
    </section>
  );
}

const CONNECTABLE: CodexStatus["state"][] = ["disconnected", "expired"];

export function Badge({ tone, children }: { tone: "ok" | "warn" | "off"; children: string }) {
  const styles = {
    ok: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    warn: "bg-amber-50 text-amber-800 ring-amber-200",
    off: "bg-slate-100 text-slate-600 ring-slate-200",
  }[tone];
  return <span className={`rounded-sm px-2.5 py-0.5 text-xs font-semibold ${styles}`}>{children}</span>;
}

function State({
  status,
  busy,
  onLogout,
  onRetry,
}: {
  status: CodexStatus;
  busy: boolean;
  onLogout: () => void;
  onRetry: () => void;
}) {
  switch (status.state) {
    case "not_configured":
      return (
        <div className="space-y-1">
          <Badge tone="off">Service Codex non installé</Badge>
          <p className="text-slate-600">
            Démarrez le service <code>codex</code> sur le serveur (<code>COMPOSE_PROFILES</code>) et renseignez{" "}
            <code>CODEX_APP_SERVER_URL</code> et <code>CODEX_WS_TOKEN</code> : le bouton « Connecter Codex » apparaîtra
            ici.
          </p>
        </div>
      );
    case "unavailable":
      return (
        <div className="space-y-3">
          <Alert>Le service Codex est injoignable : {status.detail}</Alert>
          <Button variant="secondary" onClick={onRetry}>
            Réessayer
          </Button>
        </div>
      );
    case "connected":
      return (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <Badge tone="ok">Connecté</Badge>
            <p className="text-slate-700">
              Compte ChatGPT : <span className="font-medium">{status.email ?? "inconnu"}</span>
              {status.plan && ` · forfait ${status.plan}`}
            </p>
          </div>
          <Button variant="secondary" onClick={onLogout} disabled={busy}>
            Déconnecter
          </Button>
        </div>
      );
    default:
      return status.state === "expired" ? (
        <div className="space-y-1">
          <Badge tone="warn">Connexion expirée</Badge>
          <p className="text-slate-700">La session ChatGPT a pris fin : reconnectez Codex.</p>
        </div>
      ) : (
        <div className="space-y-1">
          <Badge tone="off">Non connecté</Badge>
          <p className="text-slate-700">Les résumés échoueront tant que Codex n’est pas connecté.</p>
        </div>
      );
  }
}

const PANEL = "rounded-xl border border-slate-200 bg-slate-50 p-4";
const PANEL_LABEL = "text-xs font-semibold uppercase tracking-wide text-slate-500";
const COPY = "rounded-lg bg-white px-3 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100";

function DeviceCode({ login, busy, onCancel }: { login: CodexLogin; busy: boolean; onCancel: () => void }) {
  const url = login.verification_url!;
  const code = login.user_code!;
  return (
    <div className="space-y-3">
      <div className={PANEL}>
        <div className={PANEL_LABEL}>1. URL de vérification OpenAI</div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <code className="break-all font-mono text-lg text-slate-900 sm:text-xl">{url}</code>
          <div className="flex items-center gap-2">
            <CopyButton text={url} label="Copier" ariaLabel="Copier l’adresse de connexion" className={COPY} />
            <a
              className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              href={url}
              target="_blank"
              rel="noreferrer"
            >
              Ouvrir OpenAI
            </a>
          </div>
        </div>
        <p className="mt-2 text-slate-500">Connectez-vous à ChatGPT sur cette page.</p>
      </div>
      <div className={PANEL}>
        <div className={PANEL_LABEL}>2. Code appareil à saisir</div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <code aria-label="Code de connexion" className="font-mono text-3xl font-semibold tracking-widest text-brand-900">
            {code}
          </code>
          <CopyButton text={code} label="Copier" ariaLabel="Copier le code" className={COPY} />
        </div>
        <p className="mt-2 text-slate-500">Une fois le code validé sur OpenAI, cette page se met à jour toute seule.</p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="flex items-center gap-2 text-slate-500">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-200 border-t-brand-600" />
          En attente de la validation… Le code expire à {hm(login.expires_at)}.
        </p>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Annuler la connexion
        </Button>
      </div>
    </div>
  );
}
