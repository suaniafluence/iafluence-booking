export type Slot = { start: string; end: string };

export type BookingInfo = { start: string; end: string; meet_url: string | null };

export type BookingContext = {
  customer: { name: string; email: string };
  purchase: {
    product_name: string;
    hours_purchased: number;
    hours_booked: number;
    hours_remaining: number;
  };
  booking: BookingInfo | null;
  consultant_name: string;
  timezone: string;
  booking_duration_min: number;
  locale: string;
  /** Confidentiality agreement: its PDF is uploaded / this customer already received it. */
  nda_available: boolean;
  nda_sent: boolean;
};

export type BookingConfirmed = BookingInfo & {
  status: "confirmed";
  hours_purchased: number;
  hours_booked: number;
  hours_remaining: number;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Connexion impossible. Vérifiez votre connexion internet puis réessayez.", "network");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : "Une erreur est survenue. Veuillez réessayer.";
    throw new ApiError(res.status, detail, body.code);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  return (await res.json().catch(() => ({}))) as T;
}

const enc = encodeURIComponent;

export const api = {
  exchangeCheckout: (sessionId: string) => request<{ token: string; locale: string }>(`/api/checkout/${enc(sessionId)}`),
  context: (token: string) => request<BookingContext>(`/api/booking/${enc(token)}`),
  availability: (token: string) => request<{ slots: Slot[] }>(`/api/availability?token=${enc(token)}`),
  /** `locale` and `timezone` (IANA, from the browser) drive the confirmation email; `nda` asks for the NDA. */
  book: (token: string, start: string, locale: string, timezone: string, nda = false) =>
    request<BookingConfirmed>("/api/bookings", {
      method: "POST",
      body: JSON.stringify({ token, start, locale, timezone, nda }),
    }),
  discoveryInfo: () => request<DiscoveryInfo>("/api/discovery"),
  discoveryAvailability: () => request<{ slots: Slot[] }>("/api/discovery/availability"),
  /** `website` is the honeypot field: always empty for people. */
  bookDiscovery: (call: DiscoveryRequest) =>
    request<BookingInfo>("/api/discovery", { method: "POST", body: JSON.stringify(call) }),
  adminLogin: (password: string) =>
    request<{ status: string }>("/api/admin/login", { method: "POST", body: JSON.stringify({ password }) }),
  adminLogout: () => request<{ status: string }>("/api/admin/logout", { method: "POST" }),
  adminOverview: () => request<AdminOverview>("/api/consultant/overview"),
  adminAddClient: (client: NewClient) =>
    request<{ purchase_id: number; booking_url: string }>("/api/consultant/clients", {
      method: "POST",
      body: JSON.stringify(client),
    }),
  adminCancelBooking: (bookingId: number, notify: boolean) =>
    request<{ status: string }>(`/api/consultant/bookings/${bookingId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ notify }),
    }),
  adminSetHours: (purchaseId: number, hoursPurchased: number) =>
    request<{ hours_purchased: number; hours_booked: number; hours_remaining: number }>(
      `/api/consultant/purchases/${purchaseId}`,
      { method: "PATCH", body: JSON.stringify({ hours_purchased: hoursPurchased }) },
    ),
  adminSetAutoSend: (customerId: number, autoSend: boolean) =>
    request<{ customer_id: number; auto_send_next_link: boolean }>(`/api/consultant/customers/${customerId}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_send_next_link: autoSend }),
    }),
  adminRetryReport: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/consultant/reports/${reportId}/retry`, { method: "POST" }),
  adminDraftWithoutSummary: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/consultant/reports/${reportId}/draft-without-summary`, {
      method: "POST",
    }),
  adminRetryReportEmail: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/consultant/reports/${reportId}/retry-email`, { method: "POST" }),
  adminSetReportSettings: (sendWithoutReview: boolean) =>
    request<{ send_without_review: boolean }>("/api/consultant/report-settings", {
      method: "PATCH",
      body: JSON.stringify({ send_without_review: sendWithoutReview }),
    }),
  adminCodexStatus: () => request<CodexStatus>("/api/admin/codex"),
  adminCodexLogin: () => request<CodexLogin>("/api/admin/codex/login", { method: "POST" }),
  adminCodexLoginStatus: (loginId: number) => request<CodexLogin>(`/api/admin/codex/login/${loginId}`),
  adminCodexCancelLogin: (loginId: number) =>
    request<CodexLogin>(`/api/admin/codex/login/${loginId}/cancel`, { method: "POST" }),
  adminCodexLogout: () => request<{ state: "disconnected" }>("/api/admin/codex/logout", { method: "POST" }),
  adminFirefliesStatus: () => request<FirefliesStatus>("/api/admin/fireflies"),
  /** Checked against Fireflies before being stored (encrypted); never sent back. */
  adminFirefliesConnect: (apiKey: string) =>
    request<FirefliesStatus>("/api/admin/fireflies", { method: "POST", body: JSON.stringify({ api_key: apiKey }) }),
  adminFirefliesDisconnect: () => request<FirefliesStatus>("/api/admin/fireflies", { method: "DELETE" }),
  /** « Autres réunions » : Fireflies recordings of the last 7 days (one Fireflies request). */
  adminMeetings: () => request<{ meetings: Meeting[] }>("/api/consultant/meetings"),
  adminCreateMeetingReport: (meeting: MeetingReportRequest) =>
    request<{ report_id: number; booking_id: number }>("/api/consultant/meetings", {
      method: "POST",
      body: JSON.stringify(meeting),
    }),
  adminNda: () => request<NdaOverview>("/api/consultant/nda"),
  /** The NDA already signed by the consultant, sent as the raw PDF. */
  adminNdaUpload: (locale: string, file: File) =>
    request<{ locale: string; filename: string; size: number }>(
      `/api/consultant/nda/documents/${enc(locale)}?filename=${enc(file.name)}`,
      { method: "PUT", body: file, headers: { "Content-Type": "application/pdf" } },
    ),
  adminNdaDelete: (locale: string) =>
    request<{ status: string }>(`/api/consultant/nda/documents/${enc(locale)}`, { method: "DELETE" }),
  adminNdaSend: (contact: { name: string; email: string; locale: string }) =>
    request<{ customer_id: number; sent_at: string }>("/api/consultant/nda/send", {
      method: "POST",
      body: JSON.stringify(contact),
    }),
  adminNdaSigned: (customerId: number, signed: boolean) =>
    request<{ customer_id: number; signed_at: string | null }>(`/api/consultant/customers/${customerId}/nda`, {
      method: "PATCH",
      body: JSON.stringify({ signed }),
    }),
  /** « Imprimer mon calendrier » : PDF of every busy period from `start` to `end` (YYYY-MM-DD, both included). */
  adminCalendarPdf: async (start: string, end: string) =>
    (await send(`/api/consultant/calendar.pdf?start=${enc(start)}&end=${enc(end)}`)).blob(),

  // --- staff sign-in (V3) ---------------------------------------------------------------------------------------
  authMethods: () => request<{ google: boolean; password: boolean }>("/api/auth/methods"),
  authMe: (role: StaffRole) => request<StaffMe>(`/api/auth/me?role=${role}`),
  authLogout: (role: StaffRole) => request<{ status: string }>(`/api/auth/logout?role=${role}`, { method: "POST" }),

  // --- admin: staff accounts and platform settings ----------------------------------------------------------
  adminUsers: () => request<{ users: StaffUser[]; google_enabled: boolean }>("/api/admin/users"),
  adminAddUser: (user: { email: string; name: string; is_admin: boolean; is_consultant: boolean }) =>
    request<StaffUser>("/api/admin/users", { method: "POST", body: JSON.stringify(user) }),
  adminUpdateUser: (id: number, patch: Partial<Pick<StaffUser, "name" | "is_admin" | "is_consultant" | "active">> & { unlink_google?: boolean }) =>
    request<StaffUser>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  adminSettings: () => request<PlatformSettings>("/api/admin/settings"),
  adminUpdateSettings: (patch: Partial<Omit<PlatformSettings, "send_without_review">>) =>
    request<PlatformSettings>("/api/admin/settings", { method: "PATCH", body: JSON.stringify(patch) }),

  // --- consultant cockpit ------------------------------------------------------------------------------------
  learners: (hidden = false) => request<LearnerList>(`/api/consultant/learners${hidden ? "?hidden=true" : ""}`),
  learner: (id: number) => request<LearnerDetail>(`/api/consultant/learners/${id}`),
  updateLearner: (id: number, patch: { notes?: string; company_name?: string }) =>
    request<{ customer_id: number; company_name: string | null; notes: string | null }>(`/api/consultant/learners/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  companySearch: (id: number, q?: string) =>
    request<{ query: string; results: CompanyProfile[] }>(
      `/api/consultant/learners/${id}/company/search${q === undefined ? "" : `?q=${enc(q)}`}`,
    ),
  companyAttach: (id: number, siren: string) =>
    request<CompanyProfile>(`/api/consultant/learners/${id}/company`, { method: "PUT", body: JSON.stringify({ siren }) }),
  companyDetach: (id: number) => request<{ status: string }>(`/api/consultant/learners/${id}/company`, { method: "DELETE" }),
  startResearch: (id: number) => request<{ status: string }>(`/api/consultant/learners/${id}/research`, { method: "POST" }),
  generatePlan: (id: number) => request<{ status: string }>(`/api/consultant/learners/${id}/plan`, { method: "POST" }),
  sendPlanMessage: (id: number, message: string) =>
    request<{ status: string }>(`/api/consultant/learners/${id}/plan/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  validatePlan: (id: number, validated: boolean) =>
    request<{ validated_at: string | null }>(`/api/consultant/learners/${id}/plan`, {
      method: "PATCH",
      body: JSON.stringify({ validated }),
    }),
};

/** Where the browser goes to sign in with Google for an area (the API redirects to Google, then back). */
export const googleSignInUrl = (role: StaffRole) => `/api/auth/google/start?role=${role}`;

export type StaffRole = "admin" | "consultant";

export type StaffMe = { id: number | null; email: string; name: string; role: StaffRole };

export type StaffUser = {
  id: number;
  email: string;
  name: string;
  is_admin: boolean;
  is_consultant: boolean;
  active: boolean;
  google_linked: boolean;
  last_login_at: string | null;
};

export type PlatformSettings = {
  send_without_review: boolean;
  reminder_enabled: boolean;
  reminder_after_days: number;
  reminder_auto_send: boolean;
  hide_after_days: number;
};

export type Level = "ok" | "info" | "attention" | "alerte";
export type Signal = { niveau: Level; texte: string };

export type LearnerStatus = "prospect" | "en_cours" | "termine" | "rembourse";

export type BookingShort = { id: number; kind: BookingKind; start: string; end: string; meet_url: string | null };

export type LearnerRow = {
  customer_id: number;
  name: string;
  email: string;
  company: string | null;
  status: LearnerStatus;
  hours_purchased: number;
  sessions_done: number;
  sessions_to_deliver: number;
  hours_to_schedule: number;
  next_session: BookingShort | null;
  last_session: BookingShort | null;
  idle_days: number | null;
  hidden: boolean;
  pace_days: number | null;
  projected_end: string | null;
  plan_status: PlanStatus | null;
  reminder_sent_at: string | null;
  alerts: Signal[];
};

export type LearnerList = {
  learners: LearnerRow[];
  hidden_count: number;
  settings: { reminder_after_days: number; hide_after_days: number; session_duration_min: number };
};

export type CompanyProfile = {
  siren: string;
  nom: string;
  sigle: string | null;
  etat: "active" | "cessee";
  date_creation: string | null;
  date_fermeture: string | null;
  categorie: string | null;
  activite_code: string | null;
  effectif: string | null;
  effectif_annee: string | null;
  adresse: string | null;
  etablissements: number | null;
  dirigeants: { nom: string; qualite: string }[];
  finances: { annee: number; ca: number | null; resultat_net: number | null }[];
  labels: string[];
  signaux: Signal[];
};

export type Research = {
  synthese: string;
  activite_reelle: string[];
  personne: { role: string; linkedin_url: string };
  entreprise: { site_web: string; linkedin_url: string };
  signaux_positifs: string[];
  points_attention: string[];
  angles_ia: string[];
  questions_a_poser: string[];
  sources: { titre: string; url: string }[];
  confiance: "faible" | "moyenne" | "elevee";
};

export type PlanStatus = "pending" | "generating" | "ready" | "failed";

export type PlanSession = {
  numero: number;
  titre: string;
  objectif: string;
  duree_min: number;
  deroule: { minutes: number; activite: string }[];
  livrable: string;
  preparation_client: string[];
};

export type PlanContent = {
  resume: string;
  objectif: string;
  diagnostic: string[];
  priorites: { titre: string; pourquoi: string; gain_attendu: string; effort: "faible" | "moyen" | "eleve" }[];
  seances: PlanSession[];
  entre_les_seances: string[];
  indicateurs: string[];
  risques: { risque: string; parade: string }[];
  outils: { nom: string; usage: string; cout: string }[];
  hypotheses_a_verifier: string[];
  questions_ouvertes: string[];
};

export type ActionPlan = {
  id: number;
  status: PlanStatus;
  busy: boolean;
  content: PlanContent | null;
  error: string | null;
  version: number;
  validated_at: string | null;
  updated_at: string | null;
  messages: { role: "consultant" | "assistant"; content: string; created_at: string | null }[];
};

export type TimelineItem = {
  booking_id: number;
  kind: BookingKind;
  status: string;
  label: string;
  start: string;
  end: string;
  meet_url: string | null;
  message: string | null;
  report: { id: number; status: ReportStatus; synthese: Synthese | null; erased: boolean } | null;
};

export type LearnerDetail = {
  customer: {
    id: number;
    name: string;
    email: string;
    company_name: string | null;
    siren: string | null;
    notes: string | null;
    auto_send_next_link: boolean;
    nda_sent_at: string | null;
    nda_signed_at: string | null;
    reminder_sent_at: string | null;
    created_at: string | null;
  };
  time: {
    status: LearnerStatus;
    hours_purchased: number;
    hours_booked: number;
    hours_to_schedule: number;
    sessions_done: number;
    sessions_to_deliver: number;
    session_duration_min: number;
    next_session: BookingShort | null;
    idle_days: number | null;
    pace_days: number | null;
    projected_end: string | null;
    hidden: boolean;
    alerts: Signal[];
  };
  purchases: {
    id: number;
    product: string;
    hours_purchased: number;
    hours_booked: number;
    hours_remaining: number;
    payment_status: string;
    amount_cents: number;
    created_at: string | null;
    booking_url: string | null;
  }[];
  timeline: TimelineItem[];
  company: CompanyProfile | null;
  company_fetched_at: string | null;
  research: { status: "running" | "ready" | "failed" | null; content: Research | null; error: string | null; updated_at: string | null };
  plan: ActionPlan | null;
};

/** Served to the signed-in consultant only (session cookie). */
export const ndaPdfUrl = (locale: string) => `/api/consultant/nda/documents/${enc(locale)}.pdf`;

export type NdaOverview = {
  documents: { locale: string; filename: string; size: number; uploaded_at: string }[];
  customers: { customer_id: number; name: string; email: string; sent_at: string; signed_at: string | null }[];
};

/** Served to the signed-in consultant only (session cookie). */
export const reportImageUrl = (reportId: number) => `/api/consultant/reports/${reportId}/image.png`;

export type ReportStatus = "waiting_transcript" | "summarizing" | "ready" | "drafted" | "failed";

export type Synthese = {
  objectifs: string[];
  points_abordes: string[];
  decisions: string[];
  actions_client: string[];
  prochaines_etapes: string[];
};

export type SessionReport = {
  id: number;
  status: ReportStatus;
  transcript_found: boolean;
  transcript_attempts: number;
  summary_attempts: number;
  next_attempt_at: string | null;
  waiting_until: string;
  error: string | null;
  synthese: Synthese | null;
  has_image: boolean;
  // failed: Gmail refused the email, which the admin can prepare again.
  delivery: "draft" | "sent" | "failed" | null;
  with_summary: boolean | null;
  drafted_at: string | null;
  erased: boolean;
};

/** session: paid consulting session; discovery: free call booked on /decouverte; meeting: booked elsewhere. */
export type BookingKind = "session" | "discovery" | "meeting";

export type FinishedSession = {
  booking_id: number;
  kind: BookingKind;
  customer: string;
  email: string;
  product: string;
  start: string;
  end: string;
  report: SessionReport | null;
};

export type CodexLoginStatus = "PENDING" | "COMPLETED" | "EXPIRED" | "DENIED" | "CANCELLED" | "ERROR";

export type CodexLogin = {
  id: number;
  status: CodexLoginStatus;
  verification_url: string | null;
  user_code: string | null;
  expires_at: string;
  error: string | null;
};

export type CodexStatus = {
  state: "connected" | "expired" | "disconnected" | "unavailable" | "not_configured";
  email: string | null;
  plan: string | null;
  detail: string | null;
  pending_login: CodexLogin | null;
};

export type FirefliesStatus = {
  state: "connected" | "disconnected";
  /** admin: key connected from this page; server: FIREFLIES_API_KEY. */
  source: "admin" | "server" | null;
  email: string | null;
  name: string | null;
  detail: string | null;
};

export type NewClient = {
  name: string;
  email: string;
  hours: number;
  product_name: string;
  amount_cents: number;
  send_link: boolean;
};

export type AdminOverview = {
  kpis: {
    payments_this_month: number;
    revenue_this_month_cents: number;
    hours_sold: number;
    hours_booked: number;
    hours_done: number;
    hours_to_schedule: number;
    hours_to_deliver: number;
  };
  upcoming: (BookingInfo & { booking_id: number; kind: BookingKind; customer: string; email: string; product: string })[];
  clients: {
    purchase_id: number;
    customer_id: number;
    name: string;
    email: string;
    product: string;
    hours_purchased: number;
    hours_booked: number;
    hours_remaining: number;
    payment_status: string;
    manual: boolean;
    auto_send_next_link: boolean;
    booking_url: string | null;
    created_at: string;
    booking: BookingInfo | null;
  }[];
  reports: { enabled: boolean; send_without_review: boolean; sessions: FinishedSession[] };
};

export type DiscoveryInfo = { consultant_name: string; timezone: string; duration_min: number; nda_available: boolean };

export type DiscoveryRequest = {
  name: string;
  email: string;
  start: string;
  message: string;
  locale: string;
  timezone: string;
  /** Box ticked: email the NDA signed by the consultant. */
  nda: boolean;
  website: string;
};

export type Meeting = {
  transcript_id: string;
  title: string | null;
  start: string;
  end: string;
  /** Guests of the recording, the admin's own addresses left out. */
  participants: string[];
  suggested_email: string | null;
  suggested_name: string | null;
  /** Set once a report was asked for (or the recording was matched to a session). */
  report_id: number | null;
};

export type MeetingReportRequest = {
  transcript_id: string;
  title: string | null;
  start: string;
  end: string;
  name: string;
  email: string;
  locale: string;
};
