import type { AdminOverview, BookingConfirmed, BookingContext, Slot } from "../api";

export const context = (over: Partial<BookingContext> = {}): BookingContext => ({
  customer: { name: "Jean Dupont", email: "jean@example.com" },
  purchase: { product_name: "Conseil IA - 5h", hours_purchased: 5, hours_booked: 0, hours_remaining: 5 },
  booking: null,
  consultant_name: "Suan Tay",
  timezone: "Europe/Paris",
  booking_duration_min: 60,
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
      customer: "Jean Dupont",
      email: "jean@example.com",
      product: "Conseil IA - 5h",
      start: "2026-10-08T14:00:00+02:00",
      end: "2026-10-08T15:00:00+02:00",
      meet_url: "https://meet.google.com/abc",
    },
    {
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
