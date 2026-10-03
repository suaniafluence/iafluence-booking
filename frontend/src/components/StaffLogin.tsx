import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, googleSignInUrl, type StaffRole } from "../api";
import { Alert, Button, Card, Layout } from "./Layout";

/** Why the API sent the browser back without a session (`?erreur=` set by /api/auth/google/callback). */
export const SIGN_IN_ERRORS: Record<string, string> = {
  non_autorise: "Cette adresse Google n’a pas accès à cet espace. Demandez à l’administrateur de l’ajouter.",
  email_non_verifie: "Votre adresse Google n’est pas vérifiée.",
  compte_different:
    "Cette adresse est liée à un autre compte Google. L’administrateur peut délier l’ancien compte depuis l’administration.",
  session_expiree: "La connexion a expiré. Recommencez.",
  annule: "Connexion annulée.",
  google: "Google n’a pas pu confirmer votre identité. Réessayez dans un instant.",
};

const TITLES: Record<StaffRole, string> = { admin: "Administration", consultant: "Espace consultant" };

export const field =
  "mt-1.5 block min-h-12 w-full rounded border-[1.5px] border-slate-300 bg-white px-3.5 py-2.5 text-base text-slate-900 transition-colors hover:border-slate-500 focus:border-brand-600 focus:outline-none focus:ring-3 focus:ring-brand-600/20";

function signInError(): string | null {
  const code = new URLSearchParams(window.location.search).get("erreur");
  return code ? (SIGN_IN_ERRORS[code] ?? "La connexion a échoué.") : null;
}

/** Google first; the admin area also offers its password as a fallback. The cockpit is Google-only. */
export function StaffLogin({ role, onSuccess }: { role: StaffRole; onSuccess: () => void }) {
  const [methods, setMethods] = useState<{ google: boolean; password: boolean } | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(signInError);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .authMethods()
      .then(setMethods)
      .catch(() => setMethods({ google: true, password: role === "admin" }));
  }, [role]);

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

  const withPassword = role === "admin" && methods?.password;
  return (
    <Layout>
      <Card className="mx-auto max-w-sm">
        <h1 className="text-2xl font-extrabold text-slate-900">{TITLES[role]}</h1>
        {error && (
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
        )}
        {methods?.google && (
          <a
            href={googleSignInUrl(role)}
            className="mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded border-[1.5px] border-slate-300 bg-white px-5 py-2.5 text-[15px] font-bold text-slate-900 transition-colors hover:border-brand-600 hover:text-brand-600"
          >
            Se connecter avec Google
          </a>
        )}
        {methods && !methods.google && !withPassword && (
          <p className="mt-6 text-sm text-slate-500">La connexion Google n’est pas configurée sur ce serveur.</p>
        )}
        {withPassword && (
          <form onSubmit={submit} className="mt-6 space-y-4 border-t border-slate-200 pt-6">
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Mot de passe de secours</span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={field}
                required
              />
            </label>
            <Button type="submit" variant="secondary" className="w-full" disabled={busy || !password}>
              {busy ? "Connexion…" : "Se connecter"}
            </Button>
          </form>
        )}
      </Card>
    </Layout>
  );
}
