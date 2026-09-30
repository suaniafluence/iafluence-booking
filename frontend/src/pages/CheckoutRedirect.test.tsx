import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import { deferred } from "../test/fixtures";
import CheckoutRedirect from "./CheckoutRedirect";

function Landing() {
  const loc = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <p>landed on {loc.pathname}</p>
      <button onClick={() => navigate(-1)}>back</button>
    </>
  );
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={["/before", url]} initialIndex={1}>
      <Link to="/reservation?session_id=cs_other">other payment</Link>
      <Routes>
        <Route path="/reservation" element={<CheckoutRedirect />} />
        <Route path="/reservation/:token" element={<Landing />} />
        <Route path="/before" element={<p>previous page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.spyOn(api, "exchangeCheckout").mockResolvedValue({ token: "tok_abc" });
});

describe("CheckoutRedirect", () => {
  it("verifies the payment then replaces the URL with the booking link", async () => {
    const pending = deferred<{ token: string }>();
    vi.mocked(api.exchangeCheckout).mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderAt("/reservation?session_id=cs_test_1");
    expect(screen.getByRole("status")).toHaveTextContent("Vérification de votre paiement…");
    expect(api.exchangeCheckout).toHaveBeenCalledWith("cs_test_1");
    pending.resolve({ token: "tok_abc" });
    expect(await screen.findByText("landed on /reservation/tok_abc")).toBeInTheDocument();

    // The Stripe return URL was replaced: "back" leaves the booking flow instead of re-verifying.
    await user.click(screen.getByRole("button", { name: "back" }));
    expect(await screen.findByText("previous page")).toBeInTheDocument();
    expect(api.exchangeCheckout).toHaveBeenCalledTimes(1);
  });

  it("explains a missing session id without offering a retry", async () => {
    renderAt("/reservation");
    expect(await screen.findByRole("alert")).toHaveTextContent("Lien incomplet : identifiant de paiement manquant.");
    expect(screen.queryByRole("button", { name: "Réessayer" })).not.toBeInTheDocument();
    expect(api.exchangeCheckout).not.toHaveBeenCalled();
  });

  it("shows the error and retries on demand", async () => {
    const retry = deferred<{ token: string }>();
    vi.mocked(api.exchangeCheckout)
      .mockRejectedValueOnce(new ApiError(404, "Paiement introuvable ou non finalisé."))
      .mockReturnValueOnce(retry.promise);
    const user = userEvent.setup();
    renderAt("/reservation?session_id=cs_test_1");
    expect(await screen.findByRole("heading", { name: "Nous n’avons pas pu vérifier votre paiement" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Paiement introuvable ou non finalisé.");

    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    // While retrying, the previous error is cleared.
    expect(await screen.findByRole("status")).toHaveTextContent("Vérification de votre paiement…");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.exchangeCheckout).toHaveBeenNthCalledWith(2, "cs_test_1");

    retry.resolve({ token: "tok_abc" });
    expect(await screen.findByText("landed on /reservation/tok_abc")).toBeInTheDocument();
  });

  it("keeps retrying as long as the customer asks (payment still being confirmed)", async () => {
    const pending = new ApiError(404, "Paiement introuvable ou non finalisé.");
    vi.mocked(api.exchangeCheckout).mockRejectedValueOnce(pending).mockRejectedValueOnce(pending).mockRejectedValueOnce(pending);
    const user = userEvent.setup();
    renderAt("/reservation?session_id=cs_test_1");
    for (let i = 0; i < 3; i++) {
      await user.click(await screen.findByRole("button", { name: "Réessayer" }));
    }
    expect(await screen.findByText("landed on /reservation/tok_abc")).toBeInTheDocument();
    expect(api.exchangeCheckout).toHaveBeenCalledTimes(4);
  });

  it("ignores the answer for a payment the page no longer shows", async () => {
    const first = deferred<{ token: string }>();
    const second = deferred<{ token: string }>();
    vi.mocked(api.exchangeCheckout).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const user = userEvent.setup();
    renderAt("/reservation?session_id=cs_test_1");
    await user.click(screen.getByRole("link", { name: "other payment" }));
    expect(api.exchangeCheckout).toHaveBeenLastCalledWith("cs_other");

    first.resolve({ token: "stale" });
    await act(() => first.promise);
    expect(screen.queryByText(/landed on/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();

    second.resolve({ token: "fresh" });
    expect(await screen.findByText("landed on /reservation/fresh")).toBeInTheDocument();
  });

  it("ignores a late error for a payment the page no longer shows", async () => {
    const first = deferred<{ token: string }>();
    vi.mocked(api.exchangeCheckout).mockReturnValueOnce(first.promise).mockReturnValueOnce(new Promise(() => {}));
    const user = userEvent.setup();
    renderAt("/reservation?session_id=cs_test_1");
    await user.click(screen.getByRole("link", { name: "other payment" }));
    first.reject(new ApiError(404, "late error"));
    await act(() => first.promise.catch(() => {}));
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
