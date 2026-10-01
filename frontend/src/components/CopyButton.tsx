import { useState } from "react";

export function CopyButton({
  text,
  label = "Copier le lien",
  ariaLabel,
  className = "font-medium text-brand-600 underline",
}: {
  text: string;
  label?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className={className}
      onClick={() => navigator.clipboard.writeText(text).then(() => setCopied(true), () => {})}
    >
      {copied ? "Copié" : label}
    </button>
  );
}
