import { createContext, useContext, useEffect, type ReactNode } from "react";
import type { ApiError } from "./api";

/** Customer-facing languages; the admin area stays in French. */
export const LANGS = ["fr", "en", "es"] as const;
export type Lang = (typeof LANGS)[number];
export const DEFAULT_LANG: Lang = "fr";

export const LANG_NAMES: Record<Lang, string> = { fr: "Français", en: "English", es: "Español" };

export const isLang = (v: unknown): v is Lang => LANGS.includes(v as Lang);

/** First supported language in the browser preferences ("es-CL" -> "es"), French otherwise. */
export function browserLang(): Lang {
  const prefs = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const p of prefs) {
    const code = p?.slice(0, 2).toLowerCase();
    if (isLang(code)) return code;
  }
  return DEFAULT_LANG;
}

const fr = {
  pageTitle: "IAfluence — Réservation",
  tagline: "Sessions de conseil IA",
  languages: "Langue",
  retry: "Réessayer",
  checkout: {
    verifying: "Vérification de votre paiement…",
    failedTitle: "Nous n’avons pas pu vérifier votre paiement",
    failedHelp:
      "Si votre paiement vient d’être effectué, patientez quelques secondes puis réessayez. Un email contenant votre lien de réservation vous est également envoyé.",
    missingId: "Lien incomplet : identifiant de paiement manquant.",
  },
  booking: {
    loading: "Chargement de votre réservation…",
    unavailableTitle: "Lien de réservation indisponible",
    unavailableHelp:
      "Vérifiez que vous utilisez bien le lien reçu par email après votre paiement. En cas de problème, répondez simplement à cet email.",
  },
  welcome: {
    kicker: "Paiement reçu",
    title: "Votre conseil IA est confirmé",
    received: "Votre paiement a bien été reçu.",
    choose: "Choisissez maintenant le créneau de votre première session de conseil de 1 heure.",
    next: "Si vous avez acheté plusieurs heures, un lien pour réserver la séance suivante vous sera envoyé par email après chaque session.",
    cta: "Choisir mon créneau",
    nextKicker: "Conseil IA",
    nextTitle: "Réservez votre prochaine session",
    nextChoose: "Choisissez le créneau de votre prochaine session de conseil de 1 heure.",
  },
  allUsed: {
    title: "Toutes vos heures ont été utilisées",
    body: (site: ReactNode) => <>Merci pour votre confiance. Pour poursuivre avec de nouvelles heures de conseil, rendez-vous sur {site}.</>,
  },
  policy:
    "Toute séance réservée est due. Vous pouvez la déplacer gratuitement jusqu’à 24 h avant son début en répondant à l’email de confirmation ; passé ce délai, ou en cas d’absence, l’heure est considérée comme consommée.",
  summary: {
    service: "Prestation",
    serviceName: "Conseil IA",
    purchased: "Heures achetées",
    firstSession: "Première session",
    nextSession: "Prochaine session",
    remainingAfter: "Heures restantes après cette session",
    scheduled: "Heures planifiées",
    remaining: "Heures restantes",
  },
  picker: {
    title: "Choisissez votre créneau",
    parisTimes: "Session de 1 heure · horaires à l’heure de Paris",
    localTimes: (city: string) => `Session de 1 heure · horaires à l’heure de ${city}, heure de Paris en dessous`,
    searching: "Recherche des disponibilités…",
    none: "Aucun créneau n’est disponible pour le moment. Revenez un peu plus tard ou répondez à l’email de confirmation pour convenir d’un horaire.",
    days: "Jours disponibles",
  },
  time: {
    paris: "Paris",
    localClock: (city: string) => `À l’heure de ${city}`,
    parisClock: (when: string) => `Heure de Paris : ${when}`,
  },
  confirm: {
    title: "Votre rendez-vous",
    with: (name: string) => `Conseil IA avec ${name}`,
    sendTo: (email: ReactNode) => <>L’invitation et le lien de visioconférence seront envoyés à {email}.</>,
    change: "Changer de créneau",
    submit: "Confirmer le rendez-vous",
    submitting: "Confirmation…",
  },
  done: {
    title: "Rendez-vous confirmé",
    sent: (email: ReactNode) => <>Une invitation calendrier et un email de confirmation ont été envoyés à {email}.</>,
    next: "Un lien pour réserver la séance suivante vous sera envoyé par email après cette session.",
  },
  notFound: {
    title: "Page introuvable",
    body: (site: ReactNode) => <>Utilisez le lien de réservation reçu après votre paiement, ou contactez-nous à {site}.</>,
  },
  errors: {
    payment_not_found: "Paiement introuvable ou non finalisé.",
    invalid_token: "Ce lien de réservation est invalide ou a expiré.",
    already_booked: "Votre première session est déjà réservée.",
    no_hours_left: "Toutes vos heures ont déjà été planifiées.",
    slot_invalid: "Ce créneau n’est pas proposé à la réservation.",
    slot_taken: "Ce créneau vient d’être réservé ou n’est plus disponible. Veuillez choisir un autre horaire.",
    calendar_unavailable: "Les disponibilités sont momentanément indisponibles. Veuillez réessayer dans quelques minutes.",
    calendar_write_failed: "Le rendez-vous n’a pas pu être créé. Veuillez réessayer.",
    network: "Connexion impossible. Vérifiez votre connexion internet puis réessayez.",
    generic: "Une erreur est survenue. Veuillez réessayer.",
  } as Record<string, string>,
};

export type Messages = typeof fr;

const en: Messages = {
  pageTitle: "IAfluence — Booking",
  tagline: "AI consulting sessions",
  languages: "Language",
  retry: "Try again",
  checkout: {
    verifying: "Checking your payment…",
    failedTitle: "We couldn’t confirm your payment",
    failedHelp:
      "If you’ve only just paid, wait a few seconds and try again. We’re also sending your booking link by email.",
    missingId: "This link is incomplete: the payment reference is missing.",
  },
  booking: {
    loading: "Loading your booking…",
    unavailableTitle: "Booking link unavailable",
    unavailableHelp:
      "Please make sure you’re using the link we emailed you after your payment. If something’s not right, simply reply to that email.",
  },
  welcome: {
    kicker: "Payment received",
    title: "Your AI consulting is confirmed",
    received: "Thank you, we’ve received your payment.",
    choose: "Now pick a time for your first one-hour consulting session.",
    next: "If you purchased more than one hour, you’ll receive an email after each session with a link to book the next one.",
    cta: "Choose a time",
    nextKicker: "AI consulting",
    nextTitle: "Book your next session",
    nextChoose: "Choose a time for your next one-hour consulting session.",
  },
  allUsed: {
    title: "You’ve used all your hours",
    body: (site: ReactNode) => <>Thank you for your trust. To continue with more consulting hours, visit {site}.</>,
  },
  policy:
    "Every booked session is due. You can reschedule free of charge up to 24 hours before it starts by replying to the confirmation email; after that, or if you don’t attend, the hour counts as used.",
  summary: {
    service: "Service",
    serviceName: "AI consulting",
    purchased: "Hours purchased",
    firstSession: "First session",
    nextSession: "Next session",
    remainingAfter: "Hours left after this session",
    scheduled: "Hours scheduled",
    remaining: "Hours left",
  },
  picker: {
    title: "Choose a time",
    parisTimes: "One-hour session · times shown in Paris time",
    localTimes: (city: string) => `One-hour session · times shown in ${city} time, with Paris time below`,
    searching: "Finding available times…",
    none: "There are no times available right now. Please check back a little later, or reply to your confirmation email and we’ll find a time that suits you.",
    days: "Available days",
  },
  time: {
    paris: "Paris",
    localClock: (city: string) => `${city} time`,
    parisClock: (when: string) => `Paris time: ${when}`,
  },
  confirm: {
    title: "Your appointment",
    with: (name: string) => `AI consulting with ${name}`,
    sendTo: (email: ReactNode) => <>The invitation and video call link will be sent to {email}.</>,
    change: "Choose another time",
    submit: "Confirm appointment",
    submitting: "Confirming…",
  },
  done: {
    title: "Appointment confirmed",
    sent: (email: ReactNode) => <>A calendar invitation and a confirmation email have been sent to {email}.</>,
    next: "After this session, you’ll receive an email with a link to book the next one.",
  },
  notFound: {
    title: "Page not found",
    body: (site: ReactNode) => <>Please use the booking link you received after your payment, or get in touch via {site}.</>,
  },
  errors: {
    payment_not_found: "We couldn’t find this payment, or it hasn’t gone through yet.",
    invalid_token: "This booking link is invalid or has expired.",
    already_booked: "Your first session is already booked.",
    no_hours_left: "All your hours have already been scheduled.",
    slot_invalid: "This time can’t be booked.",
    slot_taken: "Sorry, this time has just been taken or is no longer available. Please choose another one.",
    calendar_unavailable: "We can’t load availability right now. Please try again in a few minutes.",
    calendar_write_failed: "We couldn’t create your appointment. Please try again.",
    network: "Can’t connect. Please check your internet connection and try again.",
    generic: "Something went wrong. Please try again.",
  },
};

const es: Messages = {
  pageTitle: "IAfluence — Reserva",
  tagline: "Sesiones de asesoría en IA",
  languages: "Idioma",
  retry: "Reintentar",
  checkout: {
    verifying: "Verificando su pago…",
    failedTitle: "No hemos podido verificar su pago",
    failedHelp:
      "Si acaba de pagar, espere unos segundos y vuelva a intentarlo. También le enviaremos su enlace de reserva por correo electrónico.",
    missingId: "Enlace incompleto: falta la referencia del pago.",
  },
  booking: {
    loading: "Cargando su reserva…",
    unavailableTitle: "Enlace de reserva no disponible",
    unavailableHelp:
      "Compruebe que está usando el enlace que recibió por correo electrónico después del pago. Si el problema continúa, basta con responder a ese correo.",
  },
  welcome: {
    kicker: "Pago recibido",
    title: "Su asesoría en IA está confirmada",
    received: "Hemos recibido su pago correctamente.",
    choose: "Ahora elija el día y la hora de su primera sesión de asesoría, de una hora.",
    next: "Si ha contratado varias horas, después de cada sesión le enviaremos por correo un enlace para reservar la siguiente.",
    cta: "Elegir día y hora",
    nextKicker: "Asesoría en IA",
    nextTitle: "Reserve su próxima sesión",
    nextChoose: "Elija el día y la hora de su próxima sesión de asesoría, de una hora.",
  },
  allUsed: {
    title: "Ya ha utilizado todas sus horas",
    body: (site: ReactNode) => <>Gracias por su confianza. Si desea continuar con nuevas horas de asesoría, visite {site}.</>,
  },
  policy:
    "Toda sesión reservada se considera debida. Puede cambiarla sin coste hasta 24 horas antes de su inicio respondiendo al correo de confirmación; pasado ese plazo, o si no se presenta, la hora se dará por consumida.",
  summary: {
    service: "Servicio",
    serviceName: "Asesoría en IA",
    purchased: "Horas contratadas",
    firstSession: "Primera sesión",
    nextSession: "Próxima sesión",
    remainingAfter: "Horas restantes tras esta sesión",
    scheduled: "Horas programadas",
    remaining: "Horas restantes",
  },
  picker: {
    title: "Elija día y hora",
    parisTimes: "Sesión de una hora · horario de París",
    localTimes: (city: string) => `Sesión de una hora · horas de ${city}, con la hora de París debajo`,
    searching: "Buscando horarios disponibles…",
    none: "En este momento no hay horarios disponibles. Vuelva a consultar un poco más tarde o responda al correo de confirmación y buscaremos juntos un horario.",
    days: "Días disponibles",
  },
  time: {
    paris: "París",
    localClock: (city: string) => `Hora de ${city}`,
    parisClock: (when: string) => `Hora de París: ${when}`,
  },
  confirm: {
    title: "Su cita",
    with: (name: string) => `Asesoría en IA con ${name}`,
    sendTo: (email: ReactNode) => <>Enviaremos la invitación y el enlace de la videollamada a {email}.</>,
    change: "Cambiar de horario",
    submit: "Confirmar la cita",
    submitting: "Confirmando…",
  },
  done: {
    title: "Cita confirmada",
    sent: (email: ReactNode) => <>Hemos enviado una invitación de calendario y un correo de confirmación a {email}.</>,
    next: "Después de esta sesión le enviaremos por correo un enlace para reservar la siguiente.",
  },
  notFound: {
    title: "Página no encontrada",
    body: (site: ReactNode) => <>Utilice el enlace de reserva que recibió después del pago o contacte con nosotros en {site}.</>,
  },
  errors: {
    payment_not_found: "No encontramos este pago o todavía no se ha completado.",
    invalid_token: "Este enlace de reserva no es válido o ha caducado.",
    already_booked: "Su primera sesión ya está reservada.",
    no_hours_left: "Ya se han programado todas sus horas.",
    slot_invalid: "Este horario no se puede reservar.",
    slot_taken: "Este horario se acaba de reservar o ya no está disponible. Por favor, elija otro.",
    calendar_unavailable: "Ahora mismo no podemos consultar la disponibilidad. Vuelva a intentarlo en unos minutos.",
    calendar_write_failed: "No se ha podido crear la cita. Vuelva a intentarlo.",
    network: "No hay conexión. Compruebe su conexión a internet y vuelva a intentarlo.",
    generic: "Se ha producido un error. Vuelva a intentarlo.",
  },
};

export const MESSAGES: Record<Lang, Messages> = { fr, en, es };

/** Translated text for an API error, from its code (the server's own message is French only). */
export function errorText(t: Messages, err: Pick<ApiError, "code">): string {
  return (err.code && t.errors[err.code]) || t.errors.generic;
}

const LangContext = createContext<Lang>(DEFAULT_LANG);

export function LangProvider({ lang, children }: { lang: Lang; children: ReactNode }) {
  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = MESSAGES[lang].pageTitle;
  }, [lang]);
  return <LangContext.Provider value={lang}>{children}</LangContext.Provider>;
}

export function useI18n(): { lang: Lang; t: Messages } {
  const lang = useContext(LangContext);
  return { lang, t: MESSAGES[lang] };
}
