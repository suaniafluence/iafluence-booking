import { useState, type FormEvent } from "react";
import { api, ApiError, type PastedTranscript } from "../../api";
import { Icon } from "../../components/Icon";
import { Alert, Button } from "../../components/Layout";
import { LANG_NAMES, LANGS, type Lang } from "../../i18n";

const MIN_CHARS = 200;
const MAX_CHARS = 400_000;
// 16px at least: iOS zooms into smaller fields.
const field =
  "mt-1 block w-full rounded border-[1.5px] border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900 focus:border-brand-600 focus:outline-none";
const DURATIONS = [30, 45, 60, 90, 120];

type Speakers = { count: string; names: string; text: string };

const emptySpeakers: Speakers = { count: "", names: "", text: "" };

function toPaste(s: Speakers): PastedTranscript {
  return {
    text: s.text,
    speaker_count: s.count ? Number(s.count) : null,
    speaker_names: s.names
      .split(",")
      .map((n) => n.trim())
      .filter(Boolean),
  };
}

/** Who speaks, and the transcript itself: shared by both forms. */
function SpeakersFields({ value, onChange, idPrefix }: { value: Speakers; onChange: (v: Speakers) => void; idPrefix: string }) {
  const length = value.text.trim().length;
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,14rem)_1fr]">
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Nombre d’interlocuteurs</span>
          <select value={value.count} onChange={(e) => onChange({ ...value, count: e.target.value })} className={field}>
            <option value="">Je ne sais pas</option>
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-semibold text-slate-900">Noms</span> <span className="text-slate-500">(facultatif)</span>
          <input
            value={value.names}
            onChange={(e) => onChange({ ...value, names: e.target.value })}
            className={field}
            placeholder="Suan, Marie Martin, Paul (associé)"
            autoComplete="off"
          />
          <span className="mt-1 block text-xs text-slate-500">Séparés par des virgules.</span>
        </label>
      </div>
      <div className="text-sm">
        <label htmlFor={`${idPrefix}-text`} className="font-semibold text-slate-900">
          Transcription
        </label>
        <textarea
          id={`${idPrefix}-text`}
          required
          rows={10}
          minLength={MIN_CHARS}
          maxLength={MAX_CHARS}
          value={value.text}
          onChange={(e) => onChange({ ...value, text: e.target.value })}
          className={`${field} min-h-56 resize-y leading-relaxed`}
          placeholder="Collez ici le texte de la transcription de votre téléphone…"
        />
        <span className="mt-1 flex flex-wrap justify-between gap-x-3 text-xs text-slate-500">
          <span>
            Astuce : annoncez les personnes au début de l’enregistrement (« Bonjour, je suis Suan, avec Marie et son
            associé Paul »).
          </span>
          <span className={`tabular-nums ${length > 0 && length < MIN_CHARS ? "text-red-700" : ""}`}>
            {length.toLocaleString("fr-FR")} caractère{length > 1 ? "s" : ""}
          </span>
        </span>
      </div>
    </>
  );
}

function Actions({ busy, onCancel, label }: { busy: boolean; onCancel: () => void; label: string }) {
  return (
    <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
        Annuler
      </Button>
      <Button type="submit" disabled={busy}>
        {busy ? "Envoi…" : label}
      </Button>
    </div>
  );
}

const SUBMIT_LABEL = "Attribuer les interlocuteurs et résumer";

/** Under a finished session or call of the list: its transcript, pasted from the phone. */
export function PasteForBooking({
  bookingId,
  customer,
  onCancel,
  onDone,
}: {
  bookingId: number;
  customer: string;
  onCancel: () => void;
  onDone: (message: string) => void;
}) {
  const [speakers, setSpeakers] = useState(emptySpeakers);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.adminPasteTranscript(bookingId, toPaste(speakers));
      onDone(`Transcription de ${customer} reçue : interlocuteurs puis compte rendu dans quelques minutes, en brouillon Gmail.`);
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      aria-label={`Transcription de ${customer}`}
      className="mt-3 space-y-4 rounded bg-slate-50 p-4"
    >
      <SpeakersFields value={speakers} onChange={setSpeakers} idPrefix={`paste-${bookingId}`} />
      {error && <Alert>{error}</Alert>}
      <Actions busy={busy} onCancel={onCancel} label={SUBMIT_LABEL} />
    </form>
  );
}

function localDate(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return [`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, `${pad(d.getHours())}:00`];
}

/** « Coller une transcription » : a meeting held outside the site (in person, by phone…), known only by its text. */
export function PasteMeeting({ onCreated }: { onCreated: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [date, time] = localDate(new Date(Date.now() - 3600_000));
  const initial = { name: "", email: "", title: "", date, time, duration: "60", locale: "fr" as Lang };
  const [form, setForm] = useState(initial);
  const [speakers, setSpeakers] = useState(emptySpeakers);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: HTMLInputElement | HTMLSelectElement }) =>
    setForm({ ...form, [k]: e.target.value });

  const close = () => {
    setOpen(false);
    setForm(initial);
    setSpeakers(emptySpeakers);
    setError(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const start = new Date(`${form.date}T${form.time}`);
    const end = new Date(start.getTime() + Number(form.duration) * 60_000);
    try {
      await api.adminPasteMeeting({
        ...toPaste(speakers),
        title: form.title.trim() || null,
        start: start.toISOString(),
        end: end.toISOString(),
        name: form.name,
        email: form.email,
        locale: form.locale,
      });
      onCreated(`Transcription reçue pour ${form.name} : le brouillon Gmail sera prêt dans quelques minutes.`);
      setBusy(false);
      close();
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700">
          <Icon name="mic" size={18} />
        </span>
        <div className="min-w-0">
          <h3 className="font-bold text-slate-900">Coller une transcription</h3>
          <p className="mt-1 text-sm text-slate-500">
            Une conversation enregistrée sur votre téléphone, sans les noms des interlocuteurs : l’agent retrouve qui
            parle d’après le sens, puis rédige le compte rendu comme pour Fireflies. Pour une séance de la liste
            ci-dessous, utilisez plutôt « Coller la transcription » sur sa ligne.
          </p>
        </div>
      </div>
      {!open ? (
        <Button variant="secondary" className="mt-4 w-full sm:w-auto" onClick={() => setOpen(true)}>
          Coller une transcription
        </Button>
      ) : (
        <form onSubmit={submit} aria-label="Transcription d’une autre réunion" className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Nom du destinataire</span>
              <input required value={form.name} onChange={set("name")} className={field} autoComplete="name" maxLength={255} />
            </label>
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Email</span>
              <input
                required
                type="email"
                inputMode="email"
                value={form.email}
                onChange={set("email")}
                className={field}
                autoComplete="email"
              />
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="font-semibold text-slate-900">Titre</span> <span className="text-slate-500">(facultatif)</span>
              <input value={form.title} onChange={set("title")} className={field} maxLength={255} placeholder="Rendez-vous au salon" />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <label className="col-span-2 block text-sm sm:col-span-1">
              <span className="font-semibold text-slate-900">Date</span>
              <input required type="date" value={form.date} onChange={set("date")} className={field} />
            </label>
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Début</span>
              <input required type="time" value={form.time} onChange={set("time")} className={field} />
            </label>
            <label className="block text-sm">
              <span className="font-semibold text-slate-900">Durée</span>
              <select value={form.duration} onChange={set("duration")} className={field}>
                {DURATIONS.map((d) => (
                  <option key={d} value={d}>
                    {d < 60 ? `${d} min` : `${Math.floor(d / 60)} h${d % 60 ? ` ${d % 60}` : ""}`}
                  </option>
                ))}
              </select>
            </label>
            <label className="col-span-2 block text-sm sm:col-span-1">
              <span className="font-semibold text-slate-900">Langue du compte rendu</span>
              <select value={form.locale} onChange={set("locale")} className={field}>
                {LANGS.map((l) => (
                  <option key={l} value={l}>
                    {LANG_NAMES[l]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <SpeakersFields value={speakers} onChange={setSpeakers} idPrefix="paste-meeting" />
          {error && <Alert>{error}</Alert>}
          <Actions busy={busy} onCancel={close} label={SUBMIT_LABEL} />
        </form>
      )}
    </div>
  );
}
