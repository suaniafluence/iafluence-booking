import type { LearnerStatus, Signal } from "../../api";
import { hm, longDate } from "../../format";

export const STATUS_LABELS: Record<LearnerStatus, string> = {
  prospect: "Prospect",
  en_cours: "En cours",
  termine: "Terminé",
  rembourse: "Remboursé",
};

const STATUS_STYLES: Record<LearnerStatus, string> = {
  prospect: "bg-amber-50 text-amber-800",
  en_cours: "bg-brand-50 text-brand-900",
  termine: "bg-slate-100 text-slate-700",
  rembourse: "bg-red-50 text-red-800",
};

export function StatusBadge({ status }: { status: LearnerStatus }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-bold ${STATUS_STYLES[status]}`}>{STATUS_LABELS[status]}</span>;
}

const SIGNAL_STYLES: Record<Signal["niveau"], string> = {
  ok: "bg-emerald-50 text-emerald-800",
  info: "bg-slate-100 text-slate-700",
  attention: "bg-amber-50 text-amber-800",
  alerte: "bg-red-50 text-red-800",
};

export function Signals({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {signals.map((s) => (
        <li key={s.texte} className={`rounded px-2 py-0.5 text-xs ${SIGNAL_STYLES[s.niveau]}`} data-level={s.niveau}>
          {s.texte}
        </li>
      ))}
    </ul>
  );
}

/** "Jeudi 8 octobre 2026 · 14:00" */
export const when = (iso: string) => `${longDate(iso)} · ${hm(iso)}`;

export const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;
