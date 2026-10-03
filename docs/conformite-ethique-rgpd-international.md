# Audit éthique, RGPD et international

**Version :** 1er octobre 2026  
**Périmètre :** application IAfluence Booking, paiement Stripe, Google Calendar/Meet/Gmail,
Fireflies, Codex/OpenAI, PostgreSQL et exploitation sur VPS.  
**Statut :** analyse de conformité et plan d'action, pas un avis juridique individualisé.

> Ce document distingue ce que le code permet de constater de ce qui doit être vérifié par
> contrats, paramétrage des fournisseurs et procédures humaines. Il doit être validé par le
> conseil du responsable de traitement avant mise en production internationale.

## 1. Avis exécutif (« go / no-go »)

### Avis

**No-go pour l'enregistrement/transcription automatique de clients réels tant que les points P0
ci-dessous ne sont pas clos.** La réservation simple peut être mise en service après publication
d'une information de confidentialité complète et validation des contrats sous-traitants.

Le risque principal n'est pas la prise de rendez-vous. Il vient de la chaîne
Meet → Fireflies → Codex/OpenAI → résumé/infographie → Gmail : une conversation professionnelle
peut révéler des secrets d'affaires, des données de salariés ou de tiers, voire des données
sensibles. Le fait que la transcription ne soit pas enregistrée dans PostgreSQL réduit le risque,
mais ne supprime ni sa collecte par Fireflies, ni son transfert à OpenAI, ni la copie reçue par le
client dans Gmail.

### P0 — conditions préalables à la production

1. **Identifier le responsable de traitement** (raison sociale/nom, adresse, pays,
   SIREN le cas échéant, email vie privée, DPO ou représentant UE/UK si requis) et publier une
   notice FR/EN/ES avant la collecte. Le dépôt ne contient actuellement aucune notice.
2. **Choisir et documenter une base légale par finalité**, et non une base unique pour tout :
   exécution du contrat pour paiement/réservation/prestation ; obligation légale pour les pièces
   comptables ; intérêt légitime, après test de mise en balance, ou consentement pour certains
   suivis ; **consentement explicite et préalable recommandé pour enregistrer/transcrire/analyser
   la séance**, avec une vraie séance sans bot comme alternative.
3. **Faire annoncer l'enregistrement avant l'entrée du bot et au début de la séance** ; recueillir
   une preuve horodatée distincte. Prévoir arrêt immédiat et suppression en cas de retrait. Le
   simple fait de rejoindre le rendez-vous ou d'accepter les CGV n'est pas un consentement
   suffisamment spécifique à la transcription par IA.
4. **Signer et archiver les DPA/avenants article 28** avec Stripe, Google, Fireflies, OpenAI et
   l'hébergeur ; dresser la liste de leurs sous-traitants ultérieurs, lieux de traitement,
   durées de conservation et usages d'entraînement. Désactiver contractuellement l'entraînement
   sur le contenu quand l'option existe.
5. **Cartographier chaque transfert hors EEE** : décision d'adéquation si applicable, sinon clauses
   contractuelles types (CCT/SCC), analyse d'impact du transfert (TIA) et mesures complémentaires.
   Un fournisseur « américain » n'est pas automatiquement couvert : vérifier l'entité
   contractante et sa certification au Data Privacy Framework, service par service.
6. **Réaliser une AIPD/DPIA avant activation de Fireflies/Codex.** Elle est prudente ici compte tenu
   de l'observation systématique de paroles, de l'IA générative et de la possibilité de données
   sensibles ou concernant des personnes non clientes. Consulter l'autorité si le risque élevé
   résiduel ne peut pas être réduit.
7. **Fixer puis automatiser les durées de toutes les tables et copies externes.** Seuls le résumé et
   le PNG ont aujourd'hui une purge (90 jours par défaut, désactivable avec `0`). Clients, emails,
   achats, rendez-vous, identifiants Stripe/Google/Fireflies, tokens, événements webhook, brouillons
   et sauvegardes n'ont pas de politique d'effacement applicative visible.
8. **Mettre en œuvre les droits** : point de contact et procédure vérifiée pour accès, copie,
   rectification, effacement, limitation, opposition, portabilité et retrait du consentement ;
   propagation aux fournisseurs et sauvegardes ; journal de traitement des demandes ; réponse dans
   les délais propres à chaque juridiction.
9. **Écrire le plan de violation** : qualification, conservation des preuves, contact fournisseurs,
   registre d'incidents, notification CNIL sous 72 h lorsque requise, information des personnes en
   cas de risque élevé, et délais étrangers éventuellement plus courts.
10. **Durcir l'administration** : compte nominatif, MFA/passkey, limitation de débit et alertes de
    connexion, révocation des sessions, journal d'audit, moindre privilège et procédure de départ.
    Le mot de passe partagé unique et un cookie de 12 h ne donnent ni attribution individuelle ni
    second facteur.

## 2. Cartographie des données observée dans le dépôt

| Traitement | Données | Systèmes/destinataires | Observation |
|---|---|---|---|
| Achat | nom, email, produit, prix, devise, identifiants paiement/session, statut | Stripe, API, PostgreSQL | Pas de donnée carte dans l'application ; identité et métadonnées de transaction persistées. |
| Réservation | token porteur, langue, fuseau, dates, statut | navigateur, API, PostgreSQL | Le token dans l'URL permet l'accès au dossier de réservation ; il doit être traité comme un secret. |
| Disponibilités | plages occupées | Google Calendar, API | Bonne minimisation en mode normal : free/busy seulement. L'impression admin lit davantage de métadonnées. |
| Rendez-vous | nom, email, date, événement, URL Meet | Google Calendar/Meet, PostgreSQL, Gmail | Google reçoit l'identité du client et la finalité du rendez-vous. |
| Enregistrement | voix, propos, participants, email, lien Meet | Fireflies | Contenu potentiellement sensible et informations de tiers. La conservation chez Fireflies reste à vérifier. |
| Génération IA | transcription, nom, contexte contractuel, numéro de séance, heures restantes | Codex/OpenAI, mémoire API | Non stockée par l'application, mais effectivement communiquée au fournisseur IA. |
| Compte rendu | objectifs, décisions, actions, prochaines étapes, PNG, identifiant Fireflies | PostgreSQL, admin, Gmail/client | Purge locale à 90 jours par défaut ; les emails et brouillons sont des copies autonomes. |
| Administration | portefeuille clients, revenus, rendez-vous, liens porteurs, comptes rendus | administrateur | Concentration importante de données et absence d'audit nominatif. |
| Exploitation | logs, sauvegardes, secrets OAuth/API | VPS, Docker, éventuel prestataire | Les politiques de logs, sauvegarde, rotation et destruction ne sont pas définies dans le dépôt. |

### Flux qui ne doivent jamais apparaître dans les journaux

- transcription, prompt et réponse brute du modèle ;
- token de réservation, `session_id` Stripe et URL Meet ;
- clés API, cookies, jetons OAuth et en-têtes `Authorization` ;
- corps des webhooks, emails complets et images de compte rendu.

Les journaux d'accès nginx/Caddy situés en amont doivent masquer la query string et le segment token.
Le dépôt protège désormais le `Referer` et interdit la mise en cache des routes de réservation/API,
mais cette mesure ne purge pas les journaux déjà produits et ne configure pas le nginx hôte.

## 3. Analyse RGPD / EEE

### Rôles probables à contractualiser

- **IAfluence :** responsable de traitement pour prospects/clients, agenda, prestation et compte rendu.
- **Stripe :** rôle à ventiler selon les finalités (certains traitements propres, certains services
  rendus au marchand) conformément au contrat réellement signé.
- **Google, Fireflies, OpenAI, hébergeur/VPS :** sous-traitants pour les opérations exécutées sur
  instruction, avec possibles traitements propres à identifier dans leurs conditions.
- **Client entreprise :** une analyse au cas par cas est nécessaire si IAfluence traite, pendant le
  conseil, des données pour le compte de ce client. Un accord responsable/sous-traitant distinct
  peut alors être nécessaire ; le statut ne se déduit pas du nom commercial du service.

### Registre des finalités et bases proposées

| Finalité | Base à confirmer | Minimisation / durée proposée |
|---|---|---|
| Achat, réservation, invitation, prestation | Art. 6(1)(b), mesures précontractuelles/contrat | Données nécessaires seulement ; dossier actif pendant la relation. |
| Facturation, preuve comptable et fiscale | Art. 6(1)(c), texte national à référencer | Archive séparée et accès restreint pendant la durée légale applicable. |
| Sécurité et preuve des opérations | Art. 6(1)(f), test de mise en balance | Logs pseudonymisés 6–12 mois selon risque, avec exceptions incident documentées. |
| Enregistrement/transcription et résumé IA | Consentement Art. 6(1)(a) recommandé ; Art. 9(2)(a) si données sensibles prévisibles | Opt-in distinct, alternative sans enregistrement, transcription supprimée au plus tôt chez tous les acteurs. |
| Envoi du compte rendu demandé | Art. 6(1)(b), sous réserve que l'IA soit annoncée dans le service | Relecture humaine ; 90 jours localement est un maximum à justifier, pas un droit acquis. |
| Relance de la prestation déjà achetée | Contrat ou intérêt légitime selon le message | Cesser après exécution/objection ; distinguer du marketing. |
| Prospection de nouvelles prestations | Art. 6(1)(a) ou règle ePrivacy nationale applicable | Consentement/preuve et désinscription ; ne pas réutiliser automatiquement les données de séance. |

Références : [RGPD, texte officiel EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
(notamment art. 5, 6, 9, 12–22, 25, 28, 30, 32–36 et 44–49) ;
[CCT de la Commission européenne](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/standard-contractual-clauses-scc_fr).

### Transparence à présenter avant la réservation et avant l'enregistrement

La notice doit indiquer au minimum : identité/contact du responsable et du DPO/représentant ;
finalités et bases ; catégories de données ; caractère obligatoire ou facultatif et conséquences ;
destinataires ; pays et garanties de transfert avec moyen d'en obtenir copie ; durées ou critères ;
droits et modalités ; retrait sans effet rétroactif ; réclamation auprès de l'autorité ; source des
données indirectes ; logique et effets de toute décision automatisée pertinente.

Le message d'enregistrement doit être court et opérationnel, par exemple :

> « Avec votre accord, Fireflies va enregistrer et transcrire cette séance afin que nous préparions
> un compte rendu assisté par Codex/OpenAI. Vous pouvez refuser ou retirer votre accord à tout
> moment ; la séance aura lieu sans enregistrement et sans pénalité. Évitez de partager des données
> sensibles ou des données de tiers non autorisées. Acceptez-vous ? »

La case ne doit pas être précochée. Le système doit enregistrer la version du texte, l'heure, la
personne et la réponse, tout en permettant un refus. Pour les tiers présents, l'accord du seul
acheteur ne suffit pas : chaque participant doit être informé et une règle de réunion doit traiter
les arrivées tardives.

### Droits et effacement

Une suppression doit couvrir PostgreSQL, événements Google, brouillons/emails dans la mesure
juridiquement et techniquement possible, fichiers Fireflies, données OpenAI, exports, logs et
sauvegardes. Les données soumises à conservation légale doivent être **isolées et bloquées**, non
laissées dans l'interface opérationnelle. Une table de correspondance « donnée → système → méthode
d'effacement → délai → preuve » est requise.

Les résumés générés peuvent contenir des erreurs : fournir un canal simple de correction et ne pas
présenter l'infographie comme un procès-verbal approuvé. Une correction doit être propagée au dossier
actif et, si possible, au brouillon avant envoi.

## 4. Éthique et gouvernance de l'IA

### Principes obligatoires pour ce produit

1. **Liberté réelle :** aucune baisse de qualité, hausse de prix ou friction injustifiée si le client
   refuse l'enregistrement ou l'IA.
2. **Finalité limitée :** pas d'entraînement, scoring, profil psychologique, évaluation d'employés,
   prospection ou enrichissement CRM à partir des propos sans nouvelle analyse et base légale.
3. **Supervision humaine :** conserver le mode brouillon comme défaut. L'option d'envoi automatique
   des résumés devrait être désactivée en production jusqu'à mesure documentée de la qualité.
4. **Non-substitution :** le résumé est une aide, pas une décision juridique, RH, financière,
   médicale ou de sécurité. Les actions critiques nécessitent confirmation humaine.
5. **Exactitude et contestation :** indiquer « généré avec assistance IA et relu par … », permettre
   rectification, tracer la validation sans conserver la transcription.
6. **Confidentialité contextuelle :** interrompre l'enregistrement si un secret de tiers, une donnée
   très sensible ou une discussion hors périmètre apparaît ; former le consultant à cette règle.
7. **Tests d'équité :** tester accents, langues FR/EN/ES, interruptions et plusieurs locuteurs ;
   mesurer omissions et fausses attributions plutôt que seulement la qualité stylistique.
8. **Sécurité contre l'injection :** une transcription est une entrée hostile. Les outils Codex sont
   désactivés, ce qui est positif ; maintenir l'absence d'accès shell/web et tester les instructions
   malveillantes prononcées pendant une réunion.

### Indicateurs trimestriels

- taux d'opt-in, de refus et de retrait sans segmentation commerciale ;
- taux de résumés corrigés, bloqués avant envoi et contestés après envoi ;
- erreurs d'attribution par langue/accent et incidents de données de tiers ;
- délai médian et maximum des demandes de droits ;
- suppressions fournisseurs vérifiées, violations et quasi-incidents ;
- évolution des sous-traitants, pays, modèles et conditions contractuelles.

## 5. Hors Union européenne

L'emplacement du VPS ou le choix d'une loi française ne neutralise pas les lois du lieu des clients.
Il faut tenir une matrice « résidence/localisation, offre ciblée, volume, type de données, seuils,
représentant requis, transfert, délai d'incident ». Les régimes ci-dessous ne s'appliquent pas tous
automatiquement : seuils, exemptions B2B/PME et lois locales doivent être vérifiés avant ciblage.

| Zone | Points à qualifier avant commercialisation |
|---|---|
| Royaume-Uni | UK GDPR + Data Protection Act 2018 ; notice, base, contrats, DPIA, représentant éventuel et mécanisme de transfert UK (IDTA/Addendum ou adéquation). Voir l'[ICO](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/). |
| Suisse | LPD révisée : transparence, sécurité, sous-traitance, transferts et analyse d'impact ; vérifier représentant et notification. Voir le [PFPDT](https://www.edoeb.admin.ch/edoeb/fr/home/protection-des-donnees/grundlagen/datenschutzgesetz.html). |
| Californie / États-Unis | Qualifier seuils CCPA/CPRA, catégories « sensitive personal information », notice at collection, droits et contrats service-provider/contractor ; analyser aussi les lois des autres États et les règles d'enregistrement des communications (« one-party/two-party consent »), État par État. Source : [California Attorney General](https://oag.ca.gov/privacy/ccpa). |
| Canada / Québec | PIPEDA ou lois provinciales ; consentement valable, responsabilité des transferts, accès/correction ; au Québec, évaluation des facteurs relatifs à la vie privée avant communication hors Québec et règles de décision automatisée. Sources : [Commissariat à la protection de la vie privée du Canada](https://www.priv.gc.ca/fr/sujets-lies-a-la-protection-de-la-vie-privee/lois-sur-la-protection-des-renseignements-personnels-au-canada/) et [CAI Québec](https://www.cai.gouv.qc.ca/protection-renseignements-personnels/). |
| Brésil | LGPD : base légale par finalité, transparence, droits, opérateurs, DPO/encarregado selon règles applicables, incident et transfert international. Voir l'[ANPD](https://www.gov.br/anpd/pt-br). |
| Australie | Privacy Act et Australian Privacy Principles selon couverture ; notification des violations éligibles et transferts (APP 8). L'enregistrement est aussi régi par les lois des États/Territoires. Voir l'[OAIC](https://www.oaic.gov.au/privacy/australian-privacy-principles-guidelines). |
| Autres pays | Ne pas ouvrir une campagne mondiale par défaut. Effectuer un contrôle pays avant vente, notamment pour données biométriques/voix, localisation des données, consentement à l'enregistrement et accès gouvernemental. |

**Règle produit la plus sûre à l'international :** aucune capture audio/transcription par défaut,
opt-in explicite par participant, alternative équivalente, traitement régional lorsque disponible,
et suppression fournisseur vérifiable. L'email de réservation doit annoncer cette règle avant la
réunion, pas lorsque le bot est déjà présent.

## 6. Sécurité et protection des données dès la conception

### Contrôles déjà favorables

- token aléatoire de réservation et révocation après remboursement ;
- disponibilité Google en free/busy, avec échec fermé si un agenda répond mal ;
- transcription traitée en mémoire et non stockée/journalisée par l'application ;
- validation structurée de la sortie IA et assainissement du SVG ;
- résumé en brouillon par défaut et purge locale du résumé/PNG ;
- cookie admin `HttpOnly`, `Secure` configurable, `SameSite=Strict` et session limitée ;
- isolation réseau de Codex et outils actifs désactivés ;
- `Referrer-Policy: no-referrer`, CSP, `Permissions-Policy` et `Cache-Control: no-store` ajoutés au
  frontal pour limiter fuite, exécution tierce et cache des données.

### Écarts à traiter (P1)

- stocker uniquement **un hachage** des tokens de réservation en base et ajouter expiration/rotation ;
- éviter le `session_id` Stripe en query string ou le retirer immédiatement de l'historique après
  échange ; masquer URLs et queries dans tous les proxies/observabilités ;
- MFA et comptes admin nominatifs, rate limit distribué plutôt qu'un `sleep(1)`, verrouillage/alerte ;
- journal d'audit append-only pour lecture/export/modification/suppression/envoi des comptes rendus ;
- chiffrement et rotation des sauvegardes, restauration testée, clés séparées des données ;
- inventaire SBOM, correctifs dépendances/images, scan secrets, pentest et procédure de divulgation ;
- politique de purge couvrant les données structurées, fournisseurs et sauvegardes ;
- export et suppression assistés pour une demande de droits ;
- vérification que le nginx hôte n'écrit pas les URLs sensibles et reproduit les en-têtes de sécurité.

## 7. Plan 30 / 60 / 90 jours

### Jours 0–30 — bloquants

- nommer responsable sécurité/vie privée et propriétaire de chaque traitement ;
- remplir registre, notice multilingue, mentions d'enregistrement et registre des consentements ;
- obtenir DPA, liste de sous-traitants, lieux, mécanismes de transfert et règles d'entraînement ;
- désactiver Fireflies/Codex en production jusqu'à DPIA et procédure d'opt-in opérationnelle ;
- configurer rétention Fireflies/Gmail/OpenAI, interdire `REPORT_RETENTION_DAYS=0` en production ;
- écrire et simuler demande d'effacement + incident ; contrôler les logs nginx/Caddy.

### Jours 31–60 — réduction du risque

- réaliser DPIA/TIA et tests de nécessité/proportionnalité ;
- MFA/comptes nominatifs/audit admin, hachage et rotation des tokens ;
- jobs de purge avec rapport d'exécution et alertes ; export/effacement multi-systèmes ;
- politique clients entreprise : secrets, tiers, données sensibles, réunions multi-participants ;
- tests adversariaux IA et seuils qualité par langue avant tout envoi automatisé.

### Jours 61–90 — internationalisation contrôlée

- matrice d'applicabilité pays/États et procédure de géoblocage si l'analyse n'est pas terminée ;
- annexes UK, Suisse, Canada/Québec, Californie/États ciblés, Brésil et Australie selon marchés réels ;
- audit fournisseur annuel, exercice violation, restauration, demande de droits et retrait en séance ;
- revue indépendante et décision formelle d'acceptation des risques résiduels.

## 8. Dossier de preuve à conserver

La conformité doit être démontrable. Conserver, avec dates/version/signatures :

- registre des traitements, LIA/tests de mise en balance, DPIA, TIA et décisions de direction ;
- notices et scripts de consentement dans chaque langue, preuve de leur affichage/acceptation ;
- contrats/DPA/CCT, certifications DPF, sous-traitants ultérieurs et oppositions éventuelles ;
- durées par catégorie, rapports de purge et attestations de suppression fournisseurs ;
- registre des demandes, violations, décisions de notification et exercices ;
- revues d'accès, journaux d'audit, formations, pentests, correctifs et contrôles de sauvegarde ;
- fiches modèle IA, versions de prompts, évaluations de qualité/biais et validations humaines.

## 9. Critères de réouverture (« go »)

Le traitement Fireflies/Codex peut être activé quand les dix P0 sont clos, que la DPIA conclut à un
risque résiduel acceptable, qu'un refus n'empêche pas la séance, que chaque fournisseur peut effacer
les données, et qu'un test bout-en-bout prouve : information → choix → capture de preuve → retrait →
arrêt du bot → suppression locale et externe → traçabilité. Toute modification du modèle, de la
finalité, du pays de traitement ou des conditions fournisseur déclenche une nouvelle revue.
