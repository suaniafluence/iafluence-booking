import { useState } from "react";

export function CopyButton({
  text,
  label = "Copier le lien",
  ariaLabel,
}: {
  text: string;
  label?: string;
  ariaLabel?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className="font-medium text-brand-600 underline"
      onClick={() => navigator.clipboard.writeText(text).then(() => setCopied(true), () => {})}
    >
      {copied ? "Copié" : label}
    </button>
  );
}
