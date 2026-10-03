import { useI18n } from "../i18n";

/** Optional box: email the confidentiality agreement (NDA) already signed by the consultant. */
export function NdaBox({
  consultant,
  checked,
  onChange,
  disabled = false,
}: {
  consultant: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  return (
    <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600"
      />
      <span>
        <span className="font-medium text-slate-900">{t.nda.label(consultant)}</span>
        <span className="mt-1 block text-slate-500">{t.nda.hint}</span>
      </span>
    </label>
  );
}
