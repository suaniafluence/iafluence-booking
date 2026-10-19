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

const TRY_URL = "https://iafluence.fr/contact.html?besoin=projet";

const PERKS: { emoji: string; title: string; text: string }[] = [
  {
    emoji: "📅",
    title: "Réservez en 30 secondes",
    text: "Vos clients choisissent un créneau, l’agenda se remplit tout seul. Zéro échange de mails.",
  },
  {
    emoji: "🎙️",
    title: "Vous parlez, l’IA écrit",
    text: "La séance est transcrite, résumée et transformée en compte rendu. Vous, vous conseillez.",
  },
  {
    emoji: "✅",
    title: "Un plan d’action prêt à l’emploi",
    text: "Chaque apprenant repart avec ses prochaines étapes, et une relance au bon moment.",
  },
];

/** Base URL of the booking site: the two staff areas, next to a short pitch. Customers arrive with their own links. */
export default function Home() {
  return (
    <Layout wide>
      <div className="grid items-start gap-10 lg:grid-cols-2 lg:gap-14">
        <section className="lg:order-2">
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
        </section>

        <aside className="rounded border border-slate-200 bg-white p-6 sm:p-8 lg:order-1"aria-labelledby="pitch-title">
          <p className="text-sm font-bold uppercase tracking-wide text-brand-600">Pour les consultants IA</p>
          <h2 id="pitch-title" className="mt-2 font-display text-2xl font-extrabold leading-tight text-slate-900">
            Moins d’administratif, plus de <span className="hl">conseil</span> 🚀
          </h2>
          <p className="mt-3 text-slate-600">
            IAfluence Booking, c’est votre assistant de coulisses : il prend les rendez-vous, retient tout ce qui s’est dit
            et prépare la suite. Vous gardez le plaisir du métier, il s’occupe de la paperasse.
          </p>
          <ul className="mt-6 space-y-4">
            {PERKS.map((p) => (
              <li key={p.title} className="flex gap-3">
                <span className="text-2xl leading-none" aria-hidden="true">
                  {p.emoji}
                </span>
                <div>
                  <div className="font-bold text-slate-900">{p.title}</div>
                  <div className="text-sm text-slate-500">{p.text}</div>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-8 rounded bg-brand-50 p-5">
            <div className="font-display text-lg font-extrabold text-brand-900">Envie de voir ça en vrai ? 👀</div>
            <p className="mt-1 text-sm text-slate-600">Racontez-nous votre projet, on vous fait tester l’expérience.</p>
            <a
              href={TRY_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex min-h-11 items-center justify-center rounded border-[1.5px] border-transparent bg-brand-600 px-5 py-2.5 text-[15px] font-bold text-white transition-colors hover:bg-brand-700"
            >
              Tester maintenant →
            </a>
          </div>
        </aside>
      </div>
    </Layout>
  );
}
