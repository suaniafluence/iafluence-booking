import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, useInRouterContext, useLocation, useParams } from "react-router-dom";
import { isLang, LANG_NAMES, LANGS, useI18n } from "../i18n";

export function Layout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useI18n();
  const inRouter = useInRouterContext(); // the admin page is also rendered on its own
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className={`mx-auto ${wide ? "max-w-6xl" : "max-w-2xl"} px-4 py-4 flex items-center gap-3`}>
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-900 text-sm font-bold text-white">IA</span>
          <div className="leading-tight">
            <div className="font-semibold text-slate-900">IAfluence</div>
            <div className="text-xs text-slate-500">{t.tagline}</div>
          </div>
          {inRouter && <LanguageSwitcher />}
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-2xl"} flex-1 px-4 py-8 sm:py-12`}>{children}</main>
      <footer className="py-6 text-center text-xs text-slate-400">© IAfluence</footer>
    </div>
  );
}

/** Same page in another language: only the /fr|en|es prefix changes, the booking step is kept. */
function LanguageSwitcher() {
  const { lang } = useParams();
  const { pathname, search } = useLocation();
  const { t } = useI18n();
  if (!isLang(lang)) return null;
  const rest = pathname.slice(lang.length + 1);
  return (
    <nav aria-label={t.languages} className="ml-auto flex gap-1 text-xs font-semibold">
      {LANGS.map((l) => (
        <Link
          key={l}
          to={`/${l}${rest}${search}`}
          replace
          lang={l}
          hrefLang={l}
          aria-label={LANG_NAMES[l]}
          aria-current={l === lang ? "true" : undefined}
          className={`rounded-md px-2 py-1 transition ${
            l === lang ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          }`}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </nav>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8 ${className}`}>{children}</section>;
}

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  const styles =
    variant === "primary"
      ? "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-slate-300"
      : "bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400";
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${styles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-4 py-16 text-slate-500" role="status">
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-brand-600" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function Alert({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "info" }) {
  const styles = tone === "error" ? "bg-red-50 text-red-800 ring-red-200" : "bg-brand-50 text-brand-900 ring-brand-100";
  return (
    <div role="alert" className={`rounded-xl px-4 py-3 text-sm ring-1 ${styles}`}>
      {children}
    </div>
  );
}

export function HoursSummary({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="divide-y divide-slate-100 rounded-xl bg-slate-50 px-4 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between py-3">
          <dt className="text-slate-500">{k}</dt>
          <dd className="font-semibold text-slate-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
