import { Card, Layout } from "../components/Layout";
import { useI18n } from "../i18n";

export default function NotFound() {
  const { t } = useI18n();
  return (
    <Layout>
      <Card>
        <h1 className="text-xl font-extrabold text-slate-900">{t.notFound.title}</h1>
        <p className="mt-2 text-slate-600">
          {t.notFound.body(
            <a className="text-brand-600 underline" href="https://iafluence.fr">
              iafluence.fr
            </a>,
          )}
        </p>
      </Card>
    </Layout>
  );
}
