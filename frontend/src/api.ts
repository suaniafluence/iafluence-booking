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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Connexion impossible. Vérifiez votre connexion internet puis réessayez.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Une erreur est survenue. Veuillez réessayer.";
    throw new ApiError(res.status, detail, body.code);
  }
  return body as T;
}

const enc = encodeURIComponent;

export const api = {
  exchangeCheckout: (sessionId: string) => request<{ token: string }>(`/api/checkout/${enc(sessionId)}`),
  context: (token: string) => request<BookingContext>(`/api/booking/${enc(token)}`),
  availability: (token: string) => request<{ slots: Slot[] }>(`/api/availability?token=${enc(token)}`),
  book: (token: string, start: string) =>
    request<BookingConfirmed>("/api/bookings", { method: "POST", body: JSON.stringify({ token, start }) }),
  adminLogin: (password: string) =>
    request<{ status: string }>("/api/admin/login", { method: "POST", body: JSON.stringify({ password }) }),
  adminLogout: () => request<{ status: string }>("/api/admin/logout", { method: "POST" }),
  adminOverview: () => request<AdminOverview>("/api/admin/overview"),
  adminAddClient: (client: NewClient) =>
    request<{ purchase_id: number; booking_url: string }>("/api/admin/clients", {
      method: "POST",
      body: JSON.stringify(client),
    }),
  adminSetAutoSend: (customerId: number, autoSend: boolean) =>
    request<{ customer_id: number; auto_send_next_link: boolean }>(`/api/admin/customers/${customerId}`, {
      method: "PATCH",
      body: JSON.stringify({ auto_send_next_link: autoSend }),
    }),
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
  upcoming: (BookingInfo & { customer: string; email: string; product: string })[];
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
};
