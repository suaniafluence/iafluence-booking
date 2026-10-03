import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, ndaPdfUrl, type NdaOverview } from "../../api";
import { SectionTitle } from "../../components/Icon";
import { Alert, Button } from "../../components/Layout";
import { PARIS } from "../../format";
import { LANG_NAMES, LANGS, type Lang } from "../../i18n";
import { Badge } from "./CodexConnection";

const day = (iso: string) => new Intl.DateTimeFormat("fr-FR", { timeZone: PARIS, dateStyle: "short" }).format(new Date(iso));

const input =
  "block min-w-0 rounded border-[1.5px] border-slate-300 bg-white px-3 py-2 transition-colors hover:border-slate-500 focus:border-brand-600 focus:outline-none focus:ring-3 focus:ring-brand-600/20";

/**
 * « Accord de confidentialité » : the NDA already signed by the consultant (one PDF per language, French as the
 * fallback). Customers ask for it with a box on the discovery form or on the confirmation of their first session;
 * it can also be sent from here. They return it signed by replying to the email: tick « Signé reçu ».
 */
export function NdaAgreement() {
  const [data, setData] = useState<NdaOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [contact, setContact] = useState<{ name: string; email: string; locale: Lang }>({
    name: "",
    email: "",
    locale: "fr",
  });

  const load = useCallback(() => {
    api
      .adminNda()
      .then(setData)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      load();
      return true;
    } catch (err) {
      setError((err as ApiError).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const upload = (locale: Lang, file: File | undefined) => {
    if (file) void run(() => api.adminNdaUpload(locale, file), `NDA (${LANG_NAMES[locale]}) enregistré.`);
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (await run(() => api.adminNdaSend(contact), `NDA envoyé à ${contact.email}.`)) {
      setContact({ name: "", email: "", locale: "fr" });
    }
  };

  const docs = new Map((data?.documents ?? []).map((d) => [d.locale, d]));
  return (
    <section>
      <SectionTitle icon="file-pen">Accord de confidentialité (NDA)</SectionTitle>
      <div className="mt-3 space-y-5 rounded-2xl border border-slate-200 bg-white p-5 text-sm">
        <p className="max-w-[80ch] text-slate-500">
          Téléversez le NDA déjà signé de votre main. Une case « recevoir un accord de confidentialité » apparaît alors
          sur le formulaire de l’appel découverte et à la confirmation de la première séance : le PDF est envoyé par
          email, le client le renvoie signé en répondant. Le français sert aussi pour une langue sans PDF.
        </p>
        {notice && <Alert tone="info">{notice}</Alert>}
        {error && <Alert>{error}</Alert>}

        <ul className="divide-y divide-slate-200 rounded border border-slate-200">
          {LANGS.map((locale) => {
            const doc = docs.get(locale);
            return (
              <li key={locale} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="space-y-0.5">
                  <div className="font-medium text-slate-900">
                    {LANG_NAMES[locale]}
                    {locale === "fr" && <span className="ml-2 text-xs text-slate-500">obligatoire</span>}
                  </div>
                  {doc ? (
                    <a className="text-brand-600 underline" href={ndaPdfUrl(locale)} target="_blank" rel="noreferrer">
                      {doc.filename}
                    </a>
                  ) : (
                    <span className="text-slate-500">{locale === "fr" ? "Aucun PDF : la case n’est pas proposée." : "Aucun PDF : le français est envoyé."}</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <label className="cursor-pointer font-semibold text-brand-600 underline">
                    {doc ? "Remplacer" : "Téléverser le PDF"}
                    <input
                      type="file"
                      accept="application/pdf,.pdf"
                      aria-label={`PDF du NDA en ${LANG_NAMES[locale]}`}
                      className="sr-only"
                      disabled={busy}
                      onChange={(e) => {
                        upload(locale, e.target.files?.[0]);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  {doc && (
                    <button
                      type="button"
                      className="text-slate-500 underline"
                      disabled={busy}
                      onClick={() => run(() => api.adminNdaDelete(locale), `NDA (${LANG_NAMES[locale]}) supprimé.`)}
                    >
                      Supprimer
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        <form onSubmit={send} className="space-y-2">
          <div className="font-medium text-slate-900">Envoyer le NDA à un client ou à un contact</div>
          <div className="flex flex-wrap items-center gap-3">
            <input
              aria-label="Nom du destinataire"
              placeholder="Nom"
              required
              maxLength={255}
              value={contact.name}
              onChange={(e) => setContact({ ...contact, name: e.target.value })}
              className={input}
            />
            <input
              aria-label="Email du destinataire"
              placeholder="Email"
              type="email"
              required
              value={contact.email}
              onChange={(e) => setContact({ ...contact, email: e.target.value })}
              className={input}
            />
            <select
              aria-label="Langue de l’email"
              value={contact.locale}
              onChange={(e) => setContact({ ...contact, locale: e.target.value as Lang })}
              className={input}
            >
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {LANG_NAMES[l]}
                </option>
              ))}
            </select>
            <Button type="submit" className="min-h-10 px-4 text-sm" disabled={busy || !docs.has("fr")}>
              Envoyer le NDA
            </Button>
          </div>
        </form>

        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="min-w-full text-left">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">Destinataire</th>
                <th className="px-4 py-2.5 font-medium">Envoyé le</th>
                <th className="px-4 py-2.5 font-medium">Statut</th>
                <th className="px-4 py-2.5 font-medium">Signé reçu</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data?.customers.map((c) => (
                <tr key={c.customer_id}>
                  <td className="px-4 py-2.5">
                    <div className="font-bold text-slate-900">{c.name}</div>
                    <div className="text-slate-500">{c.email}</div>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{day(c.sent_at)}</td>
                  <td className="px-4 py-2.5">
                    {c.signed_at ? (
                      <Badge tone="ok">{`Signé (${day(c.signed_at)})`}</Badge>
                    ) : (
                      <Badge tone="warn">En attente du retour</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={`NDA signé reçu de ${c.name}`}
                      checked={c.signed_at !== null}
                      disabled={busy}
                      onChange={(e) =>
                        run(
                          () => api.adminNdaSigned(c.customer_id, e.target.checked),
                          e.target.checked ? `NDA de ${c.name} marqué signé.` : `NDA de ${c.name} remis en attente.`,
                        )
                      }
                      className="h-[18px] w-[18px] accent-brand-600"
                    />
                  </td>
                </tr>
              ))}
              {data?.customers.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-5 text-center text-slate-500">
                    Aucun NDA envoyé pour le moment.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
