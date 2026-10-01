import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, type FirefliesStatus } from "../../api";
import { Alert, Button } from "../../components/Layout";
import { Badge } from "./CodexConnection";

/**
 * « Connexion Fireflies » : the API key that lets the session reports read the transcripts of the sessions.
 * Fireflies has no OAuth for its API: the key is pasted once, checked against Fireflies, then kept encrypted on the
 * server and never shown again.
 */
export function FirefliesConnection() {
  const [status, setStatus] = useState<FirefliesStatus | null>(null);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api
      .adminFirefliesStatus()
      .then(setStatus)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<FirefliesStatus>, done: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setStatus(await action());
      setKey("");
      setNotice(done);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const connect = (e: FormEvent) => {
    e.preventDefault();
    void run(
      () => api.adminFirefliesConnect(key),
      "Fireflies est connecté : les transcriptions des séances seront récupérées automatiquement.",
    );
  };
  const disconnect = () => run(api.adminFirefliesDisconnect, "Fireflies est déconnecté.");

  return (
    <section>
      <h2 className="text-lg font-semibold text-slate-900">Connexion Fireflies</h2>
      <div className="mt-3 space-y-4 rounded-2xl border border-slate-200 bg-white p-5 text-sm">
        <div className="max-w-2xl space-y-1">
          <h3 className="text-base font-semibold text-slate-900">Récupérer les transcriptions des séances</h3>
          <p className="text-slate-500">
            Fireflies enregistre vos séances Google Meet. Après chaque séance, l’application récupère la transcription
            et la confie à l’agent Codex, qui rédige la synthèse. La clé API est vérifiée auprès de Fireflies, conservée
            chiffrée sur le serveur et n’est jamais réaffichée.
          </p>
        </div>
        {notice && <Alert tone="info">{notice}</Alert>}
        {error && <Alert>{error}</Alert>}
        {!status && !error && <p className="text-slate-500">Vérification de la connexion…</p>}
        {status?.state === "connected" && (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <Badge tone="ok">Connecté</Badge>
              <p className="text-slate-700">
                {status.source === "server" ? (
                  <>
                    Clé définie sur le serveur (<code>FIREFLIES_API_KEY</code>).
                  </>
                ) : (
                  <>
                    Compte Fireflies : <span className="font-medium">{status.email ?? "inconnu"}</span>
                    {status.name && ` · ${status.name}`}
                  </>
                )}
              </p>
            </div>
            {status.source === "admin" && (
              <Button variant="secondary" onClick={disconnect} disabled={busy}>
                Déconnecter
              </Button>
            )}
          </div>
        )}
        {status?.state === "disconnected" && (
          <form onSubmit={connect} className="space-y-3">
            <div className="space-y-1">
              <Badge tone="off">Non connecté</Badge>
              {status.detail && <p className="text-amber-800">{status.detail}</p>}
            </div>
            <div>
              <label htmlFor="fireflies-key" className="font-medium text-slate-900">
                Clé API Fireflies
              </label>
              <p className="text-slate-500">
                Dans Fireflies : <span className="font-medium">Settings → Developer settings → API key</span>, puis
                copiez la clé ici.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <input
                  id="fireflies-key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  maxLength={512}
                  required
                  className="block min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 font-mono focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600"
                />
                <Button type="submit" disabled={busy || !key.trim()}>
                  {busy ? "Vérification…" : "Connecter Fireflies"}
                </Button>
              </div>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
