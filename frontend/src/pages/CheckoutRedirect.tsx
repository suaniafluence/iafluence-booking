import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { Alert, Button, Card, Layout, Spinner } from "../components/Layout";
import { errorText, isLang, useI18n } from "../i18n";

export default function CheckoutRedirect() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { lang, t } = useI18n();
  const sessionId = params.get("session_id");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!sessionId) {
      setError(t.checkout.missingId);
      return;
    }
    let cancelled = false;
    setError(null);
    api
      .exchangeCheckout(sessionId)
      // The language chosen on iafluence.fr travelled with the payment.
      .then(({ token, locale }) => !cancelled && navigate(`/${isLang(locale) ? locale : lang}/reservation/${token}`, { replace: true }))
      .catch((e: ApiError) => !cancelled && setError(errorText(t, e)));
    return () => {
      cancelled = true;
    };
  }, [sessionId, attempt, navigate, lang, t]);

  return (
    <Layout>
      {error ? (
        <Card>
          <h1 className="text-xl font-semibold text-slate-900">{t.checkout.failedTitle}</h1>
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
          <p className="mt-4 text-sm text-slate-600">{t.checkout.failedHelp}</p>
          {sessionId && (
            <Button className="mt-6" onClick={() => setAttempt((n) => n + 1)}>
              {t.retry}
            </Button>
          )}
        </Card>
      ) : (
        <Spinner label={t.checkout.verifying} />
      )}
    </Layout>
  );
}
