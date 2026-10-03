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
  adminOverview: () => request<AdminOverview>("/api/admin/overview"),
  adminAddClient: (client: NewClient) =>
    request<{ purchase_id: number; booking_url: string }>("/api/admin/clients", {
      method: "POST",
      body: JSON.stringify(client),
    }),
  adminCancelBooking: (bookingId: number, notify: boolean) =>
    request<{ status: string }>(`/api/admin/bookings/${bookingId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ notify }),
    }),
  adminSetHours: (purchaseId: number, hoursPurchased: number) =>
    request<{ hours_purchased: number; hours_booked: number; hours_remaining: number }>(
      `/api/admin/purchases/${purchaseId}`,
      { method: "PATCH", body: JSON.stringify({ hours_purchased: hoursPurchased }) },
    ),
  adminSetAutoSend: (customerId: number, autoSend: boolean) =>
    request<{ customer_id: number; auto_send_next_link: boolean }>(`/api/admin/customers/${customerId}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_send_next_link: autoSend }),
    }),
  adminRetryReport: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/admin/reports/${reportId}/retry`, { method: "POST" }),
  adminDraftWithoutSummary: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/admin/reports/${reportId}/draft-without-summary`, {
      method: "POST",
    }),
  adminRetryReportEmail: (reportId: number) =>
    request<{ id: number; status: ReportStatus }>(`/api/admin/reports/${reportId}/retry-email`, { method: "POST" }),
  adminSetReportSettings: (sendWithoutReview: boolean) =>
    request<{ send_without_review: boolean }>("/api/admin/report-settings", {
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
  adminMeetings: () => request<{ meetings: Meeting[] }>("/api/admin/meetings"),
  adminCreateMeetingReport: (meeting: MeetingReportRequest) =>
    request<{ report_id: number; booking_id: number }>("/api/admin/meetings", {
      method: "POST",
      body: JSON.stringify(meeting),
    }),
  adminNda: () => request<NdaOverview>("/api/admin/nda"),
  /** The NDA already signed by the consultant, sent as the raw PDF. */
  adminNdaUpload: (locale: string, file: File) =>
    request<{ locale: string; filename: string; size: number }>(
      `/api/admin/nda/documents/${enc(locale)}?filename=${enc(file.name)}`,
      { method: "PUT", body: file, headers: { "Content-Type": "application/pdf" } },
    ),
  adminNdaDelete: (locale: string) =>
    request<{ status: string }>(`/api/admin/nda/documents/${enc(locale)}`, { method: "DELETE" }),
  adminNdaSend: (contact: { name: string; email: string; locale: string }) =>
    request<{ customer_id: number; sent_at: string }>("/api/admin/nda/send", {
      method: "POST",
      body: JSON.stringify(contact),
    }),
  adminNdaSigned: (customerId: number, signed: boolean) =>
    request<{ customer_id: number; signed_at: string | null }>(`/api/admin/customers/${customerId}/nda`, {
      method: "PATCH",
      body: JSON.stringify({ signed }),
    }),
  /** « Imprimer mon calendrier » : PDF of every busy period from `start` to `end` (YYYY-MM-DD, both included). */
  adminCalendarPdf: async (start: string, end: string) =>
    (await send(`/api/admin/calendar.pdf?start=${enc(start)}&end=${enc(end)}`)).blob(),
};

/** Served to the logged-in admin only (session cookie on /api/admin). */
export const ndaPdfUrl = (locale: string) => `/api/admin/nda/documents/${enc(locale)}.pdf`;

export type NdaOverview = {
  documents: { locale: string; filename: string; size: number; uploaded_at: string }[];
  customers: { customer_id: number; name: string; email: string; sent_at: string; signed_at: string | null }[];
};

/** Served to the logged-in admin only (session cookie on /api/admin). */
export const reportImageUrl = (reportId: number) => `/api/admin/reports/${reportId}/image.png`;

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
