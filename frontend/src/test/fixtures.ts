import type {
  AdminOverview,
  BookingConfirmed,
  BookingContext,
  CodexLogin,
  CodexStatus,
  FinishedSession,
  FirefliesStatus,
  SessionReport,
  Slot,
} from "../api";

export const context = (over: Partial<BookingContext> = {}): BookingContext => ({
  customer: { name: "Jean Dupont", email: "jean@example.com" },
  purchase: { product_name: "Conseil IA - 5h", hours_purchased: 5, hours_booked: 0, hours_remaining: 5 },
  booking: null,
  consultant_name: "Suan Tay",
  timezone: "Europe/Paris",
  booking_duration_min: 60,
  locale: "fr",
  nda_available: false,
  nda_sent: false,
  ...over,
});

// Thursday 8 and Friday 9 October 2026, Paris time (UTC+2).
export const slots: Slot[] = [
  { start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T15:00:00+02:00" },
  { start: "2026-10-08T16:00:00+02:00", end: "2026-10-08T17:00:00+02:00" },
  { start: "2026-10-09T09:00:00+02:00", end: "2026-10-09T10:00:00+02:00" },
];

export const confirmed = (over: Partial<BookingConfirmed> = {}): BookingConfirmed => ({
  status: "confirmed",
  start: "2026-10-09T09:00:00+02:00",
  end: "2026-10-09T10:00:00+02:00",
  meet_url: "https://meet.google.com/abc-defg-hij",
  hours_purchased: 5,
  hours_booked: 1,
  hours_remaining: 4,
  ...over,
});

export const overview = (over: Partial<AdminOverview> = {}): AdminOverview => ({
  kpis: {
    payments_this_month: 3,
    revenue_this_month_cents: 150_000,
    hours_sold: 8,
    hours_booked: 2,
    hours_done: 1.5,
    hours_to_schedule: 6,
    hours_to_deliver: 6.5,
  },
  upcoming: [
    {
      booking_id: 21,
      kind: "session",
      customer: "Jean Dupont",
      email: "jean@example.com",
      product: "Conseil IA - 5h",
      start: "2026-10-08T14:00:00+02:00",
      end: "2026-10-08T15:00:00+02:00",
      meet_url: "https://meet.google.com/abc",
    },
    {
      booking_id: 22,
      kind: "session",
      customer: "Marie Martin",
      email: "marie@example.com",
      product: "Conseil IA - 2h",
      start: "2026-10-09T10:00:00+02:00",
      end: "2026-10-09T11:00:00+02:00",
      meet_url: null,
    },
  ],
  clients: [
    {
      purchase_id: 1,
      customer_id: 10,
      name: "Jean Dupont",
      email: "jean@example.com",
      product: "Conseil IA - 5h",
      hours_purchased: 5,
      hours_booked: 1,
      hours_remaining: 4,
      payment_status: "paid",
      manual: false,
      auto_send_next_link: true,
      booking_url: "https://booking.test/reservation/tokJ",
      created_at: "2026-10-02T12:00:00+02:00",
      booking: { start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T15:00:00+02:00", meet_url: null },
    },
    {
      purchase_id: 2,
      customer_id: 11,
      name: "Paul Rembourse",
      email: "paul@example.com",
      product: "Conseil IA - 1h",
      hours_purchased: 1,
      hours_booked: 0,
      hours_remaining: 1,
      payment_status: "refunded",
      manual: true,
      auto_send_next_link: false,
      booking_url: null,
      created_at: "2026-10-01T12:00:00+02:00",
      booking: null,
    },
  ],
  reports: { enabled: true, send_without_review: false, sessions: [] },
  ...over,
});

export const synthese = {
  objectifs: ["Cadrer le projet d'assistant"],
  points_abordes: ["Cas d'usage prioritaires", "Choix de l'outil"],
  decisions: [],
  actions_client: ["Rassembler dix devis"],
  prochaines_etapes: ["Prototype à la prochaine séance"],
};

export const sessionReport = (over: Partial<SessionReport> = {}): SessionReport => ({
  id: 7,
  status: "drafted",
  transcript_found: true,
  transcript_attempts: 2,
  summary_attempts: 1,
  next_attempt_at: null,
  waiting_until: "2026-10-08T21:00:00+02:00",
  error: null,
  synthese,
  has_image: true,
  delivery: "draft",
  with_summary: true,
  drafted_at: "2026-10-08T15:12:00+02:00",
  erased: false,
  ...over,
});

export const finishedSession = (
  report: SessionReport | null = sessionReport(),
  over: Partial<FinishedSession> = {},
): FinishedSession => ({
  booking_id: 31,
  kind: "session",
  customer: "Marie Martin",
  email: "marie@example.com",
  product: "Conseil IA - 3h",
  start: "2026-10-08T14:00:00+02:00",
  end: "2026-10-08T15:00:00+02:00",
  report,
  ...over,
});

export const codexStatus = (over: Partial<CodexStatus> = {}): CodexStatus => ({
  state: "disconnected",
  email: null,
  plan: null,
  detail: null,
  pending_login: null,
  ...over,
});

export const firefliesStatus = (over: Partial<FirefliesStatus> = {}): FirefliesStatus => ({
  state: "disconnected",
  source: null,
  email: null,
  name: null,
  detail: null,
  ...over,
});

export const codexLogin = (over: Partial<CodexLogin> = {}): CodexLogin => ({
  id: 3,
  status: "PENDING",
  verification_url: "https://auth.openai.com/codex/device",
  user_code: "ABCD-1234",
  expires_at: "2026-10-05T06:15:00+00:00",
  error: null,
  ...over,
});

/** A promise plus its resolve/reject, to control when a mocked API call settles. */
export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
