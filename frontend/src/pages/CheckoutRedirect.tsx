import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { Alert, Button, Card, Layout, Spinner } from "../components/Layout";

export default function CheckoutRedirect() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const sessionId = params.get("session_id");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!sessionId) {
      setError("Lien incomplet : identifiant de paiement manquant.");
      return;
    }
    let cancelled = false;
    setError(null);
    api
      .exchangeCheckout(sessionId)
      .then(({ token }) => !cancelled && navigate(`/reservation/${token}`, { replace: true }))
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [sessionId, attempt, navigate]);

  return (
    <Layout>
      {error ? (
        <Card>
          <h1 className="text-xl font-semibold text-slate-900">Nous n’avons pas pu vérifier votre paiement</h1>
          <div className="mt-4">
            <Alert>{error}</Alert>
          </div>
          <p className="mt-4 text-sm text-slate-600">
            Si votre paiement vient d’être effectué, patientez quelques secondes puis réessayez. Un email contenant votre
            lien de réservation vous est également envoyé.
          </p>
          {sessionId && (
            <Button className="mt-6" onClick={() => setAttempt((n) => n + 1)}>
              Réessayer
            </Button>
          )}
        </Card>
      ) : (
        <Spinner label="Vérification de votre paiement…" />
      )}
    </Layout>
  );
}
