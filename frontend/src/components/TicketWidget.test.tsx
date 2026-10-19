import { act, render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { isTokenPage, TicketWidget } from "./TicketWidget";

const script = () => document.getElementById("iafluence-ticket-script") as HTMLScriptElement | null;

const renderAt = (url: string) => {
  const router = createMemoryRouter([{ path: "*", element: <TicketWidget /> }], { initialEntries: [url] });
  render(<RouterProvider router={router} />);
  return router;
};

afterEach(() => {
  script()?.remove();
  document.getElementById("iafluence-ticket-root")?.remove();
});

describe("isTokenPage", () => {
  it.each(["/fr/reservation/tok", "/en/reservation/tok/", "/reservation/tok"])("%s carries a booking token", (p) =>
    expect(isTokenPage(p)).toBe(true),
  );
  it.each(["/", "/admin", "/consultant", "/fr/decouverte", "/reservation", "/es/reservation", "/fr/reservationx"])(
    "%s does not",
    (p) => expect(isTokenPage(p)).toBe(false),
  );
});

describe("TicketWidget", () => {
  it("loads the widget once, as the booking app", () => {
    renderAt("/fr/decouverte");
    expect(script()?.src).toBe("https://tickets.iafluence.fr/static/ticket.js");
    expect(script()?.dataset.app).toBe("booking");
    renderAt("/admin");
    expect(document.querySelectorAll("#iafluence-ticket-script")).toHaveLength(1);
  });

  it("never loads it on a booking link opened directly", () => {
    renderAt("/fr/reservation/tok");
    expect(script()).toBeNull();
  });

  it("hides it on a booking link, and shows it again when leaving", async () => {
    const router = renderAt("/fr/reservation");
    const host = document.createElement("div");
    host.id = "iafluence-ticket-root";
    document.body.append(host);
    await act(() => router.navigate("/fr/reservation/tok"));
    expect(host.style.display).toBe("none");
    await act(() => router.navigate("/fr/decouverte"));
    expect(host.style.display).toBe("");
  });

  it("hides it when it finishes loading after the visitor reached a booking link", async () => {
    const router = renderAt("/fr/reservation");
    await act(() => router.navigate("/fr/reservation/tok"));
    const host = document.createElement("div");
    host.id = "iafluence-ticket-root";
    document.body.append(host);
    script()!.dispatchEvent(new Event("load"));
    expect(host.style.display).toBe("none");
  });
});
