import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, useInRouterContext, useLocation, useParams } from "react-router-dom";
import { isLang, LANG_NAMES, LANGS, useI18n } from "../i18n";

export function Layout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useI18n();
  const inRouter = useInRouterContext(); // the admin page is also rendered on its own
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-brand-900 text-white">
        <div className={`mx-auto ${wide ? "max-w-6xl" : "max-w-2xl"} flex min-h-[68px] items-center gap-3 px-4`}>
          <span className="flex rounded bg-white px-1.5 py-1">
            <img src="/logo.jpg" alt="" className="block h-7 w-[34px] object-contain" />
          </span>
          <div className="leading-none">
            <div className="font-display text-xl font-bold">IAfluence</div>
            <div className="mt-[3px] text-[11px] font-medium leading-tight text-slate-300">{t.tagline}</div>
          </div>
          {inRouter && <LanguageSwitcher />}
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-2xl"} flex-1 px-4 py-8 sm:py-10`}>{children}</main>
      <footer className="py-6 text-center text-xs text-slate-500">© IAfluence</footer>
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
    <nav aria-label={t.languages} className="ml-auto flex gap-0.5 text-xs font-semibold">
      {LANGS.map((l) => (
        <Link
          key={l}
          to={`/${l}${rest}${search}`}
          replace
          lang={l}
          hrefLang={l}
          aria-label={LANG_NAMES[l]}
          aria-current={l === lang ? "true" : undefined}
          className={`flex min-h-8 items-center px-1.5 ${
            l === lang ? "text-white underline underline-offset-4" : "text-slate-300 hover:text-brand-400"
          }`}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </nav>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded border border-slate-200 bg-white p-6 sm:p-7 ${className}`}>{children}</section>;
}

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  const styles =
    variant === "primary"
      ? "border-transparent bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
      : "border-slate-300 bg-white text-slate-900 hover:border-brand-600 hover:text-brand-600 disabled:opacity-50";
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded border-[1.5px] px-5 py-2.5 text-[15px] font-bold leading-tight transition-colors focus:outline-none focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-brand-400 active:translate-y-px disabled:pointer-events-none ${styles} ${className}`}
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
  const styles = tone === "error" ? "bg-red-50 text-red-800" : "bg-brand-50 text-brand-900";
  return (
    <div role="alert" className={`rounded px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function HoursSummary({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="divide-y divide-slate-200 rounded bg-slate-50 px-4 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between py-3">
          <dt className="text-slate-500">{k}</dt>
          <dd className="font-bold text-slate-900 tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
