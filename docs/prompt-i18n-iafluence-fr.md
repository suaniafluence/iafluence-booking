# Prompt : internationaliser iafluence.fr (FR / EN / ES)

> À coller dans une session Claude Code ouverte sur le dépôt du site **iafluence.fr**.

---

Je veux internationaliser le site iafluence.fr en **français (langue principale), anglais et espagnol**, sans perdre le référencement actuel, et en gardant les calendriers Google qui s'affichent déjà sur le site.

Commence par explorer le dépôt (framework, routing, pages, composants, intégration des calendriers Google, liens de paiement Stripe, gestion des métadonnées et du sitemap). Propose-moi ensuite un plan court avant de modifier quoi que ce soit, puis travaille sur une branche `feat/i18n`.

## 1. Structure des URL (priorité SEO)

- Le français reste **à la racine**, sans changement d'URL : `https://iafluence.fr/...`. Aucune URL existante ne doit casser ni être redirigée.
- L'anglais sous `/en/`, l'espagnol sous `/es/` (sous-répertoires, pas de sous-domaine, pas de paramètre `?lang=`).
- **Slugs traduits** : `/en/ai-consulting`, `/es/consultoria-ia`, et non `/en/conseil-ia`.
- Chaque langue doit être une page HTML complète rendue côté serveur ou générée statiquement, pour que Google voie le contenu traduit sans exécuter de JavaScript.
- **Pas de redirection automatique** selon l'IP ou `Accept-Language`, car Googlebot crawle depuis les États-Unis et ne verrait que l'anglais. Au plus, un bandeau discret « This page is available in English » qu'on peut fermer, avec le choix mémorisé.

## 2. Référencement multilingue

Pour chaque page et chaque langue :

- `<html lang="fr">` / `lang="en"` / `lang="es"`.
- Balises **hreflang réciproques** dans le `<head>` : `fr`, `en`, `es` et `x-default` (vers la version française). Chaque version liste toutes les autres et elle-même. Toutes les URL sont absolues.
- **Canonical** vers soi-même : la page EN pointe vers l'URL EN, jamais vers la page FR.
- `<title>` et `<meta name="description">` **rédigés** pour chaque langue (pas une traduction mot à mot) : environ 55 caractères pour le titre et 150 pour la description, avec les mots-clés du marché visé.
- Open Graph / Twitter : `og:locale` (`fr_FR`, `en_GB`, `es_ES`), `og:locale:alternate`, ainsi que `og:title`, `og:description` et une image traduits si l'image contient du texte.
- **Données structurées JSON-LD** (Organization, ProfessionalService/Service, FAQPage, BreadcrumbList s'il y en a) traduites, avec `inLanguage`.
- **Sitemap XML** avec les alternates `xhtml:link rel="alternate" hreflang=...` pour chaque URL, référencé dans `robots.txt`.
- Les `alt` des images, les intitulés de boutons, les liens d'ancre, la page 404 et les messages de formulaire sont traduits.
- Le **sélecteur de langue** utilise de vrais liens `<a href>` crawlables vers la page équivalente (pas vers l'accueil), avec le nom de chaque langue écrit dans sa propre langue : « Français », « English », « Español ».
- Maillage interne : les liens d'une page EN pointent vers des pages EN.
- Ne pas indexer de page à moitié traduite. Si une page n'existe pas encore dans une langue, ne pas générer de hreflang vers elle.
- Recherche de mots-clés par marché, à me proposer avant de rédiger :
  - FR : « consultant IA », « conseil en intelligence artificielle »…
  - EN : « AI consultant », « AI consulting for small business »…
  - ES : « consultor de IA », « consultoría en inteligencia artificial »… (vocabulaire compris en Espagne et en Amérique latine).
- Vérifier que les performances (Core Web Vitals) ne se dégradent pas : pas de gros bundle de traductions chargé pour toutes les langues.
- À la fin, liste-moi ce que je dois faire dans Google Search Console : vérifier les nouvelles URL, soumettre le sitemap, contrôler le rapport hreflang.

## 3. Textes

- Traductions **naturelles et idiomatiques**, écrites comme par un natif, pas une traduction littérale. Garde le ton du site français.
- Anglais : international, orthographe britannique.
- Espagnol : neutre, compréhensible en Espagne et en Amérique latine, vouvoiement (« usted »), sans régionalismes.
- Centralise les textes dans des fichiers de traduction par langue (par exemple `locales/fr.json`, `en.json`, `es.json`, ou la solution i18n native du framework). Aucun texte en dur dans les composants.
- Pages légales (mentions légales, CGV, politique de confidentialité) et bandeau cookies traduits. Signale-moi ce qui demande une relecture juridique.
- Montre-moi les textes EN et ES pour relecture avant de les publier.

## 4. Calendriers Google déjà affichés

- Ils doivent continuer à fonctionner à l'identique en français.
- S'il s'agit d'iframes `calendar.google.com/calendar/embed` : ajouter `hl=fr|en|es` selon la langue de la page.
- **Fuseau horaire** : beaucoup de visiteurs EN/ES ne sont pas en France (Royaume-Uni, États-Unis, Australie, Chili…). Paramètre `ctz=` réglé sur le fuseau du visiteur (`Intl.DateTimeFormat().resolvedOptions().timeZone`, injecté côté client), avec un texte qui précise l'heure de Paris. Teste au moins avec `Australia/Sydney` (+8 à +10 h selon la saison, changement de date fréquent) et `America/Santiago` (-4 à -6 h, heure d'été inversée par rapport à l'Europe).
- Si les calendriers sont rendus autrement (API, widget, page de prise de RDV), applique les mêmes principes : langue de la page, fuseau du visiteur, et l'heure de Paris en rappel.

## 5. Paiement Stripe vers booking.iafluence.fr

Le site de réservation `booking.iafluence.fr` est déjà multilingue : il lit la langue dans la session Stripe et envoie le client vers `/{fr|en|es}/reservation/{token}`.

- Les **4 Payment Links Stripe existants restent les mêmes**, on n'en crée pas de nouveaux.
- Sur chaque page, chaque bouton d'achat ajoute la langue de la page à l'URL du Payment Link :
  - FR : `https://buy.stripe.com/xxxx?locale=fr&client_reference_id=fr`
  - EN : `https://buy.stripe.com/xxxx?locale=en&client_reference_id=en`
  - ES : `https://buy.stripe.com/xxxx?locale=es&client_reference_id=es`

  `locale` affiche la page de paiement Stripe dans la bonne langue. `client_reference_id` transmet la langue de façon fiable au site de réservation.
- Centralise les 4 URL de base dans un seul fichier de config. Ne touche pas à l'URL de redirection après paiement configurée dans Stripe : `https://booking.iafluence.fr/reservation?session_id={CHECKOUT_SESSION_ID}`.
- Les prix restent en euros. Propose seulement, sans l'activer, l'« Adaptive Pricing » Stripe si c'est pertinent.

## 6. Vérification

- Build sans erreur, et aucun lien interne cassé dans les 3 langues (crawl local).
- Contrôle automatique des hreflang et canonicals : script ou test qui parcourt toutes les pages et vérifie la réciprocité.
- Valider le JSON-LD (structure conforme schema.org).
- Captures d'écran FR / EN / ES sur bureau et mobile.
- Parcours complet en local : page EN, puis clic « Buy », puis vérifier que l'URL Stripe contient `locale=en&client_reference_id=en`.
- Récapitulatif final : ce qui a été fait, ce qu'il me reste à faire (Search Console, relecture des textes, relecture juridique).
