import { Card, Layout } from "../components/Layout";

export default function NotFound() {
  return (
    <Layout>
      <Card>
        <h1 className="text-xl font-semibold text-slate-900">Page introuvable</h1>
        <p className="mt-2 text-slate-600">
          Utilisez le lien de réservation reçu après votre paiement, ou contactez-nous à{" "}
          <a className="text-brand-600 underline" href="https://iafluence.fr">iafluence.fr</a>.
        </p>
      </Card>
    </Layout>
  );
}
