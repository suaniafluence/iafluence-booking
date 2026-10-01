import { useEffect, type ReactNode } from "react";
import { Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "./api";
import { Layout, Spinner } from "./components/Layout";
import { browserLang, isLang, LangProvider, useI18n } from "./i18n";
import Admin from "./pages/Admin";
import CheckoutRedirect from "./pages/CheckoutRedirect";
import NotFound from "./pages/NotFound";
import Reservation from "./pages/Reservation";

export default function App() {
  return (
    <Routes>
      <Route path="/:lang/reservation" element={<WithLang><CheckoutRedirect /></WithLang>} />
      <Route path="/:lang/reservation/:token" element={<WithLang><Reservation /></WithLang>} />
      {/* Stripe's return URL is the same for every language: the purchase knows the language. */}
      <Route path="/reservation" element={<LangProvider lang={browserLang()}><CheckoutRedirect /></LangProvider>} />
      {/* Booking links emailed before the site was multilingual. */}
      <Route path="/reservation/:token" element={<LangProvider lang={browserLang()}><LegacyBookingLink /></LangProvider>} />
      <Route path="/admin" element={<Admin />} />
      <Route path="*" element={<LangProvider lang={browserLang()}><NotFound /></LangProvider>} />
    </Routes>
  );
}

function WithLang({ children }: { children: ReactNode }) {
  const { lang } = useParams();
  if (!isLang(lang)) {
    return (
      <LangProvider lang={browserLang()}>
        <NotFound />
      </LangProvider>
    );
  }
  return <LangProvider lang={lang}>{children}</LangProvider>;
}

function LegacyBookingLink() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();

  useEffect(() => {
    let cancelled = false;
    api
      .context(token)
      .then((c) => (isLang(c.locale) ? c.locale : browserLang()))
      // An invalid link still lands on the booking page, which explains the error.
      .catch(() => browserLang())
      .then((lang) => !cancelled && navigate(`/${lang}/reservation/${token}`, { replace: true }));
    return () => {
      cancelled = true;
    };
  }, [token, navigate]);

  return (
    <Layout>
      <Spinner label={t.booking.loading} />
    </Layout>
  );
}
