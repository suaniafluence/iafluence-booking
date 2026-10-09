import type {
  ActionPlan,
  AdminOverview,
  CompanyProfile,
  LearnerDetail,
  LearnerList,
  LearnerRow,
  PlanContent,
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
  reports: { enabled: true, paste_enabled: true, send_without_review: false, sessions: [] },
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
  source: "fireflies",
  speakers: null,
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

// --- V3 cockpit ---------------------------------------------------------------------------------------------------

export const learnerRow = (over: Partial<LearnerRow> = {}): LearnerRow => ({
  customer_id: 7,
  name: "Jean Dupont",
  email: "jean@dupont-conseil.fr",
  company: "Dupont Conseil",
  status: "en_cours",
  hours_purchased: 5,
  sessions_done: 2,
  sessions_to_deliver: 3,
  hours_to_schedule: 2,
  next_session: { id: 3, kind: "session", start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T15:00:00+02:00", meet_url: null },
  last_session: null,
  idle_days: null,
  hidden: false,
  pace_days: 14,
  projected_end: "2026-11-16T08:00:00+01:00",
  plan_status: null,
  reminder_sent_at: null,
  alerts: [{ niveau: "info", texte: "Pas encore de plan d'action" }],
  ...over,
});

export const learnerList = (over: Partial<LearnerList> = {}): LearnerList => ({
  learners: [learnerRow()],
  hidden_count: 0,
  settings: { reminder_after_days: 21, hide_after_days: 60, session_duration_min: 60 },
  ...over,
});

export const company = (over: Partial<CompanyProfile> = {}): CompanyProfile => ({
  siren: "812345678",
  nom: "DUPONT CONSEIL",
  sigle: null,
  etat: "active",
  date_creation: "2015-06-01",
  date_fermeture: null,
  categorie: "PME",
  activite_code: "70.22Z",
  effectif: "3 à 5 salariés",
  effectif_annee: "2023",
  adresse: "1 rue X 69001 LYON",
  etablissements: 1,
  dirigeants: [{ nom: "Jean DUPONT", qualite: "Gérant" }],
  finances: [{ annee: 2024, ca: 300000, resultat_net: -5000 }],
  labels: ["Certifié Qualiopi"],
  signaux: [{ niveau: "attention", texte: "Résultat net négatif en 2024" }],
  ...over,
});

export const planContent = (over: Partial<PlanContent> = {}): PlanContent => ({
  resume: "Premier cas d'usage : les devis.",
  objectif: "Diviser par trois le temps des devis",
  diagnostic: ["Devis à la main (appel)"],
  priorites: [{ titre: "Devis", pourquoi: "Cité en premier", gain_attendu: "4 h/semaine", effort: "faible" }],
  seances: [
    {
      numero: 1,
      titre: "Cadrage",
      objectif: "Un livrable",
      duree_min: 60,
      deroule: [
        { minutes: 10, activite: "Point" },
        { minutes: 50, activite: "Atelier" },
      ],
      livrable: "Prototype",
      preparation_client: ["Dix devis"],
    },
  ],
  entre_les_seances: ["Tester sur trois devis"],
  indicateurs: ["Temps par devis"],
  risques: [{ risque: "RGPD", parade: "Compte pro" }],
  outils: [{ nom: "ChatGPT Team", usage: "Rédaction", cout: "30 €/mois" }],
  hypotheses_a_verifier: [],
  questions_ouvertes: ["Qui valide ?"],
  ...over,
});

export const plan = (over: Partial<ActionPlan> = {}): ActionPlan => ({
  id: 1,
  status: "ready",
  busy: false,
  content: planContent(),
  error: null,
  version: 1,
  validated_at: null,
  updated_at: "2026-10-05T08:00:00+02:00",
  messages: [{ role: "assistant", content: "Choix : les devis d'abord.", created_at: "2026-10-05T08:00:00+02:00" }],
  ...over,
});

export const learnerDetail = (over: Partial<LearnerDetail> = {}): LearnerDetail => ({
  customer: {
    id: 7,
    name: "Jean Dupont",
    email: "jean@dupont-conseil.fr",
    company_name: "Dupont Conseil",
    siren: null,
    notes: "Très pressé",
    acquisition_source: "whatsapp",
    acquisition_detail: null,
    auto_send_next_link: false,
    nda_sent_at: null,
    nda_signed_at: null,
    reminder_sent_at: null,
    created_at: "2026-09-01T10:00:00+02:00",
  },
  time: {
    status: "en_cours",
    hours_purchased: 5,
    hours_booked: 3,
    hours_to_schedule: 2,
    sessions_done: 2,
    sessions_to_deliver: 3,
    session_duration_min: 60,
    next_session: { id: 3, kind: "session", start: "2026-10-08T14:00:00+02:00", end: "2026-10-08T15:00:00+02:00", meet_url: null },
    idle_days: null,
    pace_days: 14,
    projected_end: "2026-11-16T08:00:00+01:00",
    hidden: false,
    alerts: [],
  },
  purchases: [
    {
      id: 1,
      product: "Conseil IA - 5h",
      hours_purchased: 5,
      hours_booked: 3,
      hours_remaining: 2,
      payment_status: "paid",
      amount_cents: 50000,
      created_at: "2026-09-01T10:00:00+02:00",
      booking_url: "https://booking.iafluence.fr/fr/reservation/tok",
    },
  ],
  timeline: [
    {
      booking_id: 9,
      kind: "discovery",
      status: "completed",
      label: "Appel découverte",
      start: "2026-08-25T10:00:00+02:00",
      end: "2026-08-25T10:30:00+02:00",
      meet_url: null,
      message: "Automatiser les devis",
      report: {
        id: 2,
        status: "drafted",
        erased: false,
        synthese: { objectifs: [], points_abordes: ["Devis"], decisions: ["Commencer par les devis"], actions_client: [], prochaines_etapes: [] },
      },
    },
  ],
  company: null,
  company_fetched_at: null,
  research: { status: null, content: null, error: null, updated_at: null },
  plan: null,
  ...over,
});
