import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { Layout } from "../components/Layout";

const AREAS: { to: string; icon: IconName; title: string; text: string }[] = [
  {
    to: "/consultant",
    icon: "graduation-cap",
    title: "Espace consultant",
    text: "Vos apprenants, leurs séances, les comptes rendus et les plans d’action.",
  },
  {
    to: "/admin",
    icon: "shield-check",
    title: "Administration",
    text: "Comptes, connexions Codex et Fireflies, relances.",
  },
];

/** Base URL of the booking site: the two staff areas. Customers arrive with their own links. */
export default function Home() {
  return (
    <Layout>
      <h1 className="text-[32px] font-extrabold leading-none text-slate-900">
        IAfluence <span className="hl">Booking</span>
      </h1>
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {AREAS.map((a) => (
          <Link
            key={a.to}
            to={a.to}
            className="flex flex-col gap-2 rounded border border-slate-200 bg-white p-6 transition-colors hover:border-brand-600"
          >
            <Icon name={a.icon} size={28} className="text-brand-600" />
            <span className="font-display text-xl font-extrabold text-slate-900">{a.title}</span>
            <span className="text-sm text-slate-500">{a.text}</span>
          </Link>
        ))}
      </div>
    </Layout>
  );
}
