# PROJET M2 – Agent IA Arato (conforme au cahier des charges v11) · version 16

```
PROJET M2/
├─ Backend_AgentIA/     FastAPI : agent IA, outils Python déterministes, connecteur CRM, scheduler, e-mails, rapports
├─ CRM_AgentIA/         API du CRM (port 8001) – même venv que le backend
├─ Frontend_AgentIA/    Vue 3 + TypeScript + Tailwind 4 : espace Haut responsable + simulateur CRM (démo)
├─ scripts/             setup_db.sql, verifier_versions.py, smtp_debug.py
└─ lancer_*.bat  initialiser_crm.bat  reinitialiser_app.bat
```

## Ce qui a changé par rapport à la version précédente

**Conformité au cahier des charges v9**
- **Organisation par projet (§2.6)** : un cahier validé = un projet. Le backend crée le projet *à la validation* (et non au dépôt),
  puis les tickets. Tableau de bord, synthèse, analyses, recommandations, chat, rapports et suivi temporel sont **par projet** ;
  l'agent ne reçoit jamais de données d'un autre projet (outils du chat et de l'analyse verrouillés sur le projet courant).
  `id_projet` est porté par `SuiviRetard`, `AnalyseTicket`, `SyntheseSuivi`, `Recommandation`, `ConversationChat`, `Rapport`.
- **Sélecteur de projet** dans la barre supérieure (Figure 1) ; le projet actif est mémorisé.
- **Synthèse dynamique** enrichie : problèmes, **priorités** ordonnées (calculées par Python), **risques et prédictions**,
  **évolutions depuis la dernière analyse**, recommandations ; elle ne reprend plus ticket par ticket.
- **Recommandations** : une seule recommandation ouverte par ticket (la nouvelle remplace l'ancienne non décidée) ; décision
  *Suivre / Rejeter* définitive (409 si déjà décidée) ; vérification du format, du mot « relance » et des chiffres de Python.
- **Chat** : fondé sur le projet sélectionné, mémoire des 3 derniers échanges, liens vers l'analyse des tickets cités,
  vérification automatique (chiffres issus des outils, tickets du projet, pas de « relance »), repli déterministe.
- **Suivi événementiel et temporel** par projet ; le flux d'événements du CRM porte désormais `projet_id` ;
  détection d'un CRM réinitialisé (le curseur d'événements ne bloque plus après un nouveau jeu de test).
- **Validation d'un cahier** : correction de la relance après échec partiel (plus de tickets en double, dépendances
  vers des tâches déjà créées acceptées), dépendances vers une tâche supprimée retirées automatiquement.
- **CRM** : `POST /projets` (création par l'application), `PUT /tickets/{id}/membres`, `GET /evenements/dernier`,
  dépendances limitées au même projet, règles *ouvert = plusieurs personnes / en cours = une personne*.
- **Évaluation (§4)** : taux d'acceptation/correction/rejet, écart de durée, taux de suivi/rejet, « relance », repli,
  **cloisonnement par projet** (vérifié automatiquement sur les textes produits).
- Brouillons conservés : on peut **reprendre** un cahier après rechargement de la page.

**LLM en ligne (votre PC ne supporte pas le modèle local)**
- Le fournisseur reste *un paramètre de configuration* (§1) : toute API compatible OpenAI (Groq, Google Gemini, OpenRouter…).
- Client robuste pour les offres gratuites : limitation de débit, nouvelles tentatives sur 429/5xx (respect de `Retry-After`),
  messages d'erreur explicites (clé refusée, quota, modèle introuvable), repli JSON si le modèle gère mal les appels d'outils,
  repli déterministe si le modèle reste indisponible (l'application continue de fonctionner).
- **Administration → Modèle d'IA** : liste des modèles réellement disponibles avec votre clé, choix du modèle, test de connexion.
- La clé d'API se configure **uniquement** dans `Backend_AgentIA/.env` ; elle n'est jamais affichée dans l'application.
  En production, seul `LLM_BASE_URL` change (Ollama/vLLM sur le serveur d'Arato), pas le code.

**Interface** : refonte complète (barre latérale, cartes, badges d'état, tableaux lisibles, relecture des tâches en étapes,
chat, administration), responsive, accessible (focus, `aria`, contrastes, mouvement réduit). Aucune nouvelle dépendance npm.
Le **simulateur CRM** (`/crm`, bonus du cahier) permet de jouer le rôle des membres : statut, avancement, motif d'attente
obligatoire, motif de retard, rattachement.

## Dernières évolutions de l'interface
- **Cahier des charges** = page d'accueil, bouton mis en avant en haut du menu, séparé du reste par une ligne de division.
- **Situation du projet** : synthèse structurée (état global, résumé de l'agent, priorités, risques, évolutions).
- **Tableau de bord** : palette sobre ; plus de bouton « Réévaluer » : l'évaluation est 100 % automatique (événements CRM, passage du temps, première évaluation d'un projet).
- **Administration** : journal filtrable par période ; liste des modèles d'IA et changement du modèle actif depuis l'interface.
- **CRM** : tableau pleine page ; un clic sur une ligne ouvre la fiche du ticket dans une fenêtre (consultation et modification).

## Version 16 : connexion, choix du projet, trois sections, suivi en temps réel, e-mails réparés

**Navigation**
- **Connexion obligatoire à chaque démarrage** : la session vit dans l'onglet (`sessionStorage`) ; un nouvel onglet, un redémarrage ou la
  fermeture du navigateur ramènent à la page de connexion (un simple rechargement de page garde la session). Les anciens jetons sont supprimés.
- **Page de transition « Choix du projet »** (`/projets`) : après le cahier des charges, cartes de projets (avancement, tâches en retard,
  équipe, prochaine échéance), recherche et filtres. **Aucun projet n'est ouvert par défaut** ; le sélecteur de la barre supérieure est supprimé.
- **Menu en trois sections** : *Cahier des charges* · *Suivi* (d'un projet précis) · *Administration* (générale). La barre supérieure rappelle le
  projet dans le suivi, et indique « Administration générale » dans l'administration.
- **Suivi** : Tableau de bord, Situation du projet, **Cahier du projet** (tâches, affectations, carte des dépendances), Évaluation, Chat,
  **Historique** (remplace le bouton « Administration » de cette section). L'historique est le journal de bord de CE projet uniquement
  (`GET /projets/{id}/historique`, reconstitué sans nouvelle table). Le **Journal général** reste dans Administration.

**IA**
- **Dépendances logiques** : après la décomposition, l'IA cartographie les dépendances ; Python refuse toute référence inconnue et tout cycle
  (arête par arête) ; si l'IA est indisponible, un repli suit l'ordre naturel d'un projet (cadrer → concevoir → réaliser → tester → livrer).
- **Affectation** : une ou plusieurs personnes par tâche (1 à 3, selon `nb_membres_recommande`) ; l'équipe du projet (union des membres) est affichée.

**Suivi en temps réel**
- Détection des changements du CRM toutes les **2 s** (`EVENT_POLL_SECONDS`) et réévaluation en **deux phases** : phase rapide (Python seul,
  immédiate) pour Situation, Prévisions et Recommandations ; phase IA en arrière-plan qui affine sans jamais retarder la première.
- **Situation du projet** repensée : bandeau « verdict » avec anneau animé, répartition interactive, priorités, risques filtrables,
  chronologie des évolutions (les nouveautés clignotent), recommandations en cartes.

**Corrections**
- **Bug T-039** : les tâches apparues en même temps sont regroupées dans une seule phrase (« T-039, T-040 et T-041 ont été ajoutées… ») ;
  la synthèse ne tronque plus les ajouts et une synthèse de l'IA qui en oublie une est rejetée.
- **Évaluation** : se recharge et se filtre par projet (`GET /evaluation?projet_id=`).
- **Suppression d'un projet (CRM)** : bouton « Gérer les projets » toujours visible (liste de tous les projets) en plus du bouton du filtre.
- **E-mails** : cause principale trouvée — `smtplib.SMTPException` hérite d'`OSError`, donc toute erreur d'authentification ou de STARTTLS était
  prise pour un « serveur injoignable ». Désormais : chiffrement automatique (587 → STARTTLS, 465 → SSL), un seul lot/une seule connexion,
  erreurs réelles expliquées dans le journal.
  Pour un envoi réel : renseigner `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` (voir `.env.example`).
- **Palette** : bleu nuit `#082032`, ardoise `#2C394B`, acier `#334756`, gris clair `#D2D2D2`, orange `#FF4C29` (accent et retards).
- **Tests** : 22 tests (`pytest Backend_AgentIA/tests`), dont un vrai dialogue SMTP local.
- Aucune structure de base de données modifiée.

### Corrections complémentaires (v16)
1. **Historique des cahiers** : bouton *Supprimer* sur chaque entrée (confirmation ; le projet et les tickets du CRM ne sont pas touchés).
2. **E-mails** : serveur de test `lancer_smtp_test.bat` sans aucun paquet à installer (bibliothèque standard) ; l'expéditeur devient le compte
   `MAIL_USERNAME` tant que `MAIL_FROM` garde sa valeur d'exemple (Gmail/Outlook refusent un autre expéditeur) ; indice dans le bilan si un e-mail ne part pas.
3. Après validation du cahier : un seul bouton « Choisir un projet à suivre ».
4. Menu latéral élargi de **1 cm** (18 rem + 1 cm), fixe, sans barre de défilement ; **Simulateur CRM** dans la barre supérieure.
5. Plus de défilement par sections : menu et barre fixes, la page défile normalement, sans barre visible.
6. **Modifier l'échéance** : date antérieure à aujourd'hui refusée (champ, bouton et serveur).
7. **Situation du projet** : uniquement synthèse de l'agent, priorités, risques et prédictions, évolution, recommandations ; fond blanc, aucun graphique du tableau de bord ; liseré d'accent, pastilles d'icône et accès rapides aux rubriques.
8. Texte retiré du Journal · 9. Section *E-mails* retirée de l'Administration.
10. **Évaluation** : les barres « taux » (correction, rejet des tâches, rejet des recommandations) montrent le taux lui-même (0 % = barre vide) ; les notes globales sont inchangées.
11. Le **nom du modèle** de la barre supérieure change à l'instant où l'on active un autre modèle.

### Rapports, Situation du projet, chat (v16)
- **Rapports PDF / Excel** : nouveau module `reports.py` — en-tête avec le **logo Arato** sur chaque page, mise en page sobre (bleu nuit, gris, un accent orange
  pour les retards), sections : situation générale, synthèse, priorités, risques et prédictions, évolution, recommandations, tickets. Tous les textes sont
  échappés (un « & » ou un « < » dans un titre ne casse plus le PDF), la pagination « Page X / N » est calculée en deux passes, Helvetica prend le relais si
  la police est illisible, et une erreur est expliquée à l'écran au lieu d'un simple « erreur 500 ».
  **Logo officiel** : déposer le fichier `Backend_AgentIA/app/assets/logo_arato.png` (fond transparent conseillé) ; sans fichier, une marque « arato » vectorielle est dessinée.
- **Situation du projet** : lecture éditoriale **sans cartes** — cinq rubriques numérotées séparées par un filet (synthèse, priorités, risques, évolution, recommandations),
  grande typographie, un seul accent, survols et dépliages.
- **Chat** : la zone des réponses et la saisie défilent verticalement sans barre visible.

## Version 15 : navigation, connexion, page « Situation du projet » épurée, correctifs

- **CRM** : barre de navigation ramenée en haut de page (position standard, `.navbar-night`) au lieu du menu latéral fixe.
- **Défilement** : plus de défilement global ; chaque page est découpée en sections (`data-section`) avec défilement fluide
  section par section et repère de navigation à droite (`SectionRail`, suivi de la section visible). Les cartes bornées défilent en interne.
- **Connexion** : page plus sobre et professionnelle ; bouton « œil » pour afficher/masquer le mot de passe (connexion et
  « Nouveau compte responsable », composant `PasswordInput`).
- **Situation du projet** : page volontairement simple, en 4 blocs : **Synthèse**, **Risques et prédictions**, **Évolution depuis la dernière mise à jour**,
  **Recommandations** (Suivre / Rejeter). Palette sobre, mise à jour automatique toutes les 2 s (indication « il y a X »),
  rapport PDF / Excel conservés. Elle ne reprend pas la mise en page de « Analyse d'une tâche ».
- **Vocabulaire** : « Taux de correction », « Taux de rejet », « Recommandations » (plus d'abréviations).
- **Analyse d'une tâche** : la carte Recommandation a la même hauteur que « Modifier l'échéance » ; la chronologie est dans une seule carte
  en dessous, sur toute la largeur.
- **Suivi de 100 % des tâches** : les créations de tickets du CRM déclenchent désormais l'analyse ; une erreur sur un projet ne bloque plus les
  autres ; une analyse échouée est retentée par le contrôle temporel ; plus de plafonds qui écartaient des tâches ; couverture affichée (`suivi`).
- **E-mails d'affectation** : l'envoi est consigné dans Administration → Journal, une ligne par e-mail
  (« E-mail d'affectation envoyé à … » ou « … non envoyé à … : motif »). Si le serveur SMTP est injoignable, une copie est gardée dans `data/outbox`.
  À vérifier si rien ne part : `MAIL_SERVER` / `MAIL_PORT` dans `.env` (lancer `lancer_smtp_test.bat` pour un test local).
  La fonctionnalité « Messages » (boîte intégrée) a été retirée.
- **Tests** : 15 tests (`pytest Backend_AgentIA/tests`).

## Version 14 : correctifs, interface unifiée, rapport PDF

- **Mise en page** : menu latéral réellement fixe sur toute la hauteur (`position: fixed; height: 100dvh`) ; contenu élargi (jusqu'à 1680 px) ;
  cartes « Risques et prédictions » / « Évolution globale » à hauteur bornée avec défilement interne et « Voir plus » ; page de connexion illustrée.
- **Situation du projet** : bloc « Le projet en clair » (verdict, anneau de progression, 4 chiffres expliqués simplement). Tous les chiffres sont
  calculés par Python (`app/plain.py`), jamais par l'IA.
- **Analyse d'une tâche** : chronologie à hauteur fixe avec défilement, regroupée par jour, filtrable, avec un fil de statuts (stepper).
- **Chat** : « Je réponds à partir des données reçues concernant le projet. »
- **E-mails d'affectation** : module `app/mailer.py` (smtplib) avec erreurs explicites, archivage `.eml` dans `data/outbox`,
  options `MAIL_*` dans `.env.example`. (v15 : le résultat de chaque envoi est lu dans Administration → Journal.)
- **Affectation** : une tâche peut être confiée à plusieurs personnes (`nb_membres_recommande`, 3 maximum), sans doublon.
- **CRM** : un membre se supprime s'il n'a aucun ticket non fermé (membre sans projet ou membre dont tous les tickets sont fermés) ; sinon message précis.
- **Rapport PDF** : en-tête de marque, polices Poppins embarquées (`app/fonts`), pied de page « Page X / N », tuiles de chiffres, équipe par ticket.
- **Calculs** : aucun calcul financier dans l'application ; calculs de délais/avancement revérifiés (13 → 14 tests : `pytest Backend_AgentIA/tests`).
  L'évaluation de l'IA ne porte plus que sur les cahiers validés.

## Version 13 : palette « digitale », photos, règles de gestion
- **Palette** : bleu `#5281EB`, ciel `#83CDEB`, azur `#5BB8EB`, brume `#C1C8E4`, violet `#8860CF`. Titres Poppins, texte Inter. **Aucun italique** dans l'application ; les cartes placées côte à côte ont la même hauteur.
- **Menu** : « Paramètres » (en bas, près de « Se déconnecter ») ouvre une fenêtre de changement de mot de passe. La page « Compte » (Administration) permet d'ajouter ou changer sa **photo de profil**.
- **Cahier des charges** : parcours animé en 3 étapes, analyse par phases, tâches présentées en frise ; après validation, écran « Les tickets ont bien été envoyés au CRM » avec bouton « Accéder au tableau de bord » (plus de redirection automatique).
- **CRM** : photos des membres, modification et suppression d'un membre (refusée s'il a au moins une tâche active), suppression d'un projet avec ses tickets (l'agent se met à jour tout seul).
- **Règles** : « Fermé » n'est plus choisi à la main, il s'applique à 100 % d'avancement ; l'avancement ne change que pour « Ouvert » et « En cours » ; un ticket fermé n'est plus modifiable.
- **Tableau de bord** : couleurs modérées ; « Charge par membre » en jauges circulaires fines avec photo ; colonne « Avancement déclaré » retirée du tableau (elle reste dans le graphique).
- **Analyse d'un ticket** : bandeau d'en-tête teinté, anneau d'avancement, recommandation mise en valeur, frise chronologique à icônes. **Évaluation de l'IA** : radar à 5 axes. **Situation du projet** : synthèse, risques, évolution, recommandations (sans doublon avec le tableau de bord).
- **Chat** : « Bonjour [prénom], qu'est-ce que je peux faire pour vous aujourd'hui ? », ton professionnel. **Journal** : une date précise ou « 7 derniers jours », suppression d'entrées.
- Les photos sont enregistrées sur disque (`data/photos` du CRM, `data/avatars` du backend) : aucune migration de base.

## Version 11 (suite) : nouvelle identité visuelle
- **Palette** : crème `#F7F1F0`, rose poudré `#C3A6A0`, terracotta `#A15C38`, encre `#262220` (brique réservée aux retards). Titres en serif italique (Playfair Display), texte en Inter.
- **Bouton « Détails »** rétabli dans le tableau de bord (3 colonnes : Ticket · Statut CRM · Avancement déclaré · État de l'échéance).
- **Tableau de bord** : graphiques interactifs (anneau de répartition, avancement déclaré, charge par membre).
- **Situation du projet** : anneau de répartition des tâches dans l'état global.
- **Nouvelle page « Évaluation de l'IA »** (menu) : score global et notes en **étoiles** (ou pourcentages), anneaux, explications au clic. Création des tâches et Suivi uniquement ; « Anticipation et réactivité » et « Contrôles de conformité » sont supprimés.
- **Administration** : Modèle d'IA, Journal, Comptes.
- Aucune base de données ni fonctionnalité modifiée : seul l'affichage change.

## Version 11 : corrections et refonte visuelle
- **Cahier des charges** : les critères d'acceptation ont été retirés (écran, IA, CRM). Correction du bug « expected str instance, dict found » : les tickets proposés par l'IA sont désormais tous envoyés au CRM (textes normalisés, identifiants uniques, dépendances nettoyées), puis le tableau de bord s'ouvre automatiquement.
- **Tableau de bord** : tableau allégé (Ticket · Statut CRM · Avancement déclaré · État de l'échéance), colonne « Dernier motif » retirée.
- **Recommandations** : recalculées à chaque événement CRM **et** au passage du temps (échéance à J-5, J-2, demain, dépassée…), y compris sans appel au modèle. La page « Analyse de tâche » se rafraîchit seule.
- **Situation du projet** : « Évolutions récentes » (24 h, datées) : changements de statut, d'avancement, d'échéance, nouveaux tickets, motifs documentés.
- **Analyse de tâche** : champ Projet retiré ; « Analyse de l'agent » devient « Recommandation » ; mots « Historique » et « déterministe » retirés ; texte superflu retiré de « Modifier l'échéance ».
- **CRM** : le motif de retard n'est proposé (et accepté) que si l'échéance est réellement dépassée.
- **Administration** : onglet « Seuils » retiré (valeurs par défaut 2 jours / 50 % dans `.env` : `SEUIL_JOURS`, `SEUIL_AVANCEMENT`, `HOLIDAYS`) ; « Évaluation » sans « Anticipation et réactivité » ni « Contrôles de conformité » ; **Journal vide tant qu'aucune période n'est choisie** (dates, « Aujourd'hui » ou « 7 derniers jours »).
- **Design** : interface monochrome (encre + gris), rouge réservé aux retards et erreurs ; menu clair ; pastilles à point ; tableaux aérés.
- Écarts volontaires : plusieurs comptes responsables (même droits, connexion par e-mail) ; le mot « ouvrés » n'est plus affiché (les calculs restent hors week-ends et jours fériés) ; LLM en ligne en phase de test.

## Mise à jour depuis la version précédente (Windows)

1. Remplacez les dossiers `Backend_AgentIA`, `CRM_AgentIA`, `Frontend_AgentIA`, `scripts` et les `.bat` (gardez votre `venv`,
   vos `node_modules` et vos fichiers `.env`).
2. **Le modèle de données a changé** : exécutez `reinitialiser_app.bat` (base de l'application) puis `initialiser_crm.bat` (CRM).
3. Dans `Backend_AgentIA\.env`, remplacez la section LLM par celle de `.env.example` (voir ci-dessous).
4. Frontend : `npm install` inchangé (aucune dépendance ajoutée).

## Obtenir une clé d'API gratuite

| Fournisseur | Clé | Atouts |
|---|---|---|
| **Groq** | https://console.groq.com/keys | très rapide ; quotas par minute modestes → documents courts |
| **Google Gemini** | https://aistudio.google.com/apikey | grand contexte → longs cahiers des charges (`LLM_MAX_DOC_CHARS=60000`) |
| **OpenRouter** | https://openrouter.ai/keys | modèles « :free » |

Les offres gratuites et leurs noms de modèles évoluent : après avoir collé votre clé dans `.env` et démarré le backend,
ouvrez **Administration → Modèle d'IA** : les modèles disponibles sont listés, cliquez sur **Activer** pour changer le modèle actif.
Pour de meilleurs résultats avec un modèle gratuit, préférez un modèle de **≥ 70 milliards de paramètres** et gérant les appels d'outils.

## Mise en place complète

1. PostgreSQL : `psql -U postgres -f scripts\setup_db.sql`
2. Dans `Backend_AgentIA` : `venv\Scripts\activate`, `pip install -r requirements.txt`, `copy .env.example .env`
   (renseigner `LLM_API_KEY`, changer `JWT_SECRET` et `ADMIN_PASSWORD`). Puis `copy .env.example .env` dans `CRM_AgentIA`
   (`CRM_SERVICE_KEY` identique des deux côtés).
3. `cd Frontend_AgentIA` puis `npm install`.

## Lancement

| Action | Commande |
|---|---|
| Jeu de test du CRM (réexécutable) | `initialiser_crm.bat` |
| CRM – http://localhost:8001/docs | `lancer_crm.bat` |
| Backend – http://localhost:8000/docs | `lancer_backend.bat` |
| Interface – http://localhost:5173 | `lancer_frontend.bat` |
| Réinitialiser la base de l'application | `reinitialiser_app.bat` |
| E-mails de test (facultatif) | `lancer_smtp_test.bat` |

Connexion : e-mail et mot de passe de `ADMIN_EMAIL` / `ADMIN_PASSWORD` (`.env`) pour le premier compte ; d autres comptes responsables (mêmes droits) se créent dans Administration → Comptes.

## Scénario de démonstration (5 minutes)

1. Se connecter ; choisir un projet du jeu de test : la **Situation** affiche la synthèse, les priorités et les recommandations
   (au premier démarrage, les analyses arrivent en quelques dizaines de secondes : les appels au LLM sont espacés).
2. **Tableau de bord** : statut CRM, avancement déclaré et état de l'échéance séparés ; ouvrir l'**Analyse** d'un ticket en retard.
3. Ouvrir le **simulateur CRM** (`/crm`) : passer un ticket « en attente » (motif obligatoire) ou changer l'avancement déclaré ;
   en quelques secondes la synthèse du projet concerné se met à jour (événement CRM), sans toucher aux autres projets.
4. **Chat** : « Quelles tâches sont en retard ? », « Pourquoi T-… est-elle en retard ? ».
5. **Cahier des charges** (page d'accueil) : déposer un texte → relire (durées, affectations, dépendances) → valider : le projet et les tickets sont créés.

## Limites connues

- Le code a été relu et ses fonctions déterministes testées, mais **n'a pas pu être exécuté de bout en bout dans mon environnement**
  (pas de réseau, ni PostgreSQL, ni LLM) : lancez le scénario ci-dessus et signalez toute erreur affichée.
- Avec une offre gratuite, les quotas peuvent ralentir l'analyse d'un long document ; l'application bascule alors sur ses
  repli déterministes et l'indique à l'écran (badge « déterministe »).

## Version 17 : corrections
1. **Nom de projet unique** : refusé au dépôt, à la validation (backend, 409) et dans le CRM ; contrôle en direct dans le formulaire (casse, accents et espaces ignorés).
2. **E-mails** : réglages relus à chaque envoi (modifier `.env` ne demande plus de redémarrage) ; une authentification ou un chiffrement refusé n'est plus pris pour un serveur « injoignable » ; nouvelle tentative sur panne passagère ; mot de passe d'application Gmail accepté avec espaces ; date d'échéance en français.
3. Message « vérifiez la configuration MAIL_* » supprimé de l'interface et des messages d'erreur.
4. **Rapports** : Excel refusait les caractères de contrôle (extraits de PDF/Word) et traitait « =… » comme une formule ; texte nettoyé, PDF de secours si la mise en page échoue, nom de fichier sûr, session expirée gérée.
5. **Évaluation** : les étoiles des taux montrent le pourcentage lui-même (0 % = grises) et suivent la valeur en direct.
6. **Échéance** : réévaluation immédiate (plus de tâche d'arrière-plan), l'IA n'attend plus le verrou, une synthèse IA périmée est abandonnée, et la situation se resynchronise seule dès qu'elle diffère du CRM.
7. **Synthèse exacte** : chaque tâche comptée une seule fois (retard, à surveiller, en attente, terminée).
8. **Synthèse concise** : état chiffré, évolution, une recommandation.
9. **Menu** : défilement vertical invisible (menu entier ou, en très petite hauteur, barre latérale).
Correctif CSS : accolade manquante dans `@theme` (main.css). Tests : `pytest Backend_AgentIA/tests` (32).

## Version 18 : interface et CRM
- **Dépôt du cahier** : grand message d'accueil animé, zone de dépôt vivante (fond blanc), affectation d'un ou plusieurs membres par tâche (liste cochable), bilan des e-mails à la validation (envoyés, bloqués avec cause, tâches sans membre, envoi vers le serveur de test local signalé).
- **E-mails** : tant que `MAIL_SERVER=localhost` (serveur de test), aucune vraie boîte ne reçoit de message ; renseigner un compte d'envoi réel dans `Backend_AgentIA/.env` (voir `.env.example`).
- **Tableau de bord** : état du projet en pourcentage, tuiles cliquables (filtres), échéances sur 14 jours, avancement, charge par membre.
- **Synthèse de l'agent** : « Analyse de l'agent : du constat à la décision », étape active suivie au défilement, rubriques repliables, filtre des évolutions, recommandations animées, rapport PDF/Excel avec second chemin de téléchargement (lien signé).
- **CRM** : plus de choix « Fermé (automatique 100 %) » ; plus de modification du ticket, du nom/description ni des membres rattachés. Restent : statut, avancement, motif, suppression de projet, création et suppression de membre.

## Version 19 : e-mails, rapports, cahier, connexion
- **Rapports** : le serveur génère le fichier (toute erreur est affichée telle quelle), puis le navigateur le télécharge depuis un lien prêt (`/api/rapports/fichier/...`, valable 5 min).
- **E-mails** : si `MAIL_SERVER` est `localhost`, une boîte d'envoi de test démarre avec le backend (plus de « serveur injoignable ») ; les messages sont lisibles dans `Backend_AgentIA/data/outbox`. Pour de VRAIES boîtes de réception, renseigner dans `Backend_AgentIA/.env` : `MAIL_SERVER=smtp.gmail.com`, `MAIL_PORT=587`, `MAIL_USERNAME=<compte>`, `MAIL_PASSWORD=<mot de passe d'application>`.
- **Cahier des charges** : thème clair (accent corail, aucune carte sombre). **Connexion** : photo d'équipe Arato (`Frontend_AgentIA/public/login-arato.jpg`) et formulaire sur fond blanc.

## Version 20
- **Validation** : aucune tâche sans membre n'est envoyée au CRM (blocage côté serveur, message listant les tâches ; bouton désactivé et bandeau d'alerte dans la relecture).
- **Connexion** : la photo est affichée en entier (cadre sur fond clair, rien n'est coupé).
- **Dépôt du cahier** : nouveau parcours en trois temps (nom du projet → document → lancement de l'analyse) ; la relecture garde son allure précédente.

## Version 21
- Dépôt du cahier : retour au design de la v19 (grand message animé, 3 étapes), avec des touches de couleur claires (pastilles pêche/bleu/vert, carte structurée en blocs numérotés 1 et 2, zone de dépôt teintée).
- Connexion : la photo occupe tout le panneau (plein cadre, rien n'est coupé) ; l'image `public/login-arato.jpg` a été prolongée en hauteur à partir de la photo d'origine.

## Version 22
- Fond blanc identique sur toutes les pages.
- Dépôt du cahier et tableau de bord : palette réduite (blanc, gris ardoise, une seule touche d'orange ; le rouge-orangé ne marque que le retard).

## Version 23
- Le fond dégradé gris est rétabli et identique sur toutes les pages (y compris dépôt, tableau de bord et synthèse).

## Version 24
- Synthèse de l'agent : navigation en pastilles (rubrique active en noir), parcours de l'agent et chaque rubrique dans une carte blanche, liseré orange et compteur par rubrique, survol des lignes avec repère orange. Contenu inchangé.

## Version 25
- Synthèse de l'agent : nouvelle mise en page « cockpit » sans cartes : rail vertical fixe à gauche (suit le défilement), verdict de l'agent avec indice de santé (jauge), carte des tâches (échéance × avancement, zone « échéance dépassée »), barres de retard dans les priorités, risques en deux colonnes par niveau. L'API `/projets/{id}/synthese` renvoie en plus la liste `taches`.

## Version 26
- Synthèse de l'agent : une seule colonne, stepper horizontal fixe (étape active en noir), bandeau « verdict » avec jauge, carte des tâches avec légende, rubriques à pastille numérotée orange et compteur, risques en deux colonnes.

## Version 27
- Synthèse de l'agent, mise en page « dossier » monochrome : verdict + 4 grands chiffres + jauge, carte des tâches, puis 4 onglets (Signaux, Risques, Changements, Actions) qui montrent une rubrique à la fois. L'orange ne marque plus que le retard.

## Version 28
- Synthèse de l'agent : contenu identique à la v24 (parcours, priorités, risques, évolution, recommandations), sans ajout. Nouvelle mise en page : parcours fixe en haut servant d'onglets (étape affichée en noir), une rubrique affichée à la fois, sans cartes, orange réservé aux numéros et aux niveaux de risque élevé.

## Version 29
- Synthèse de l'agent : contenu identique à la v24, mise en page en grille 2 × 2 (priorités, risques, évolution, recommandations) visible d'un coup, parcours de l'agent en bandeau en haut ; la rubrique survolée ou choisie est marquée en noir. Sans cartes, presque monochrome.

## Version 30
- Synthèse de l'agent : contenu de la v24 inchangé. Nouveau diagramme de flux (une barre par étape, hauteur proportionnelle au nombre, rubans reliés, grains animés, étape active allumée, étapes cliquables) et rubriques disposées le long d'un fil vertical numéroté.

## Version 31
- Synthèse de l'agent : contenu de la v24 inchangé. Anneau de l'analyse (parts cliquables) + détail des 5 étapes, puis rubriques en cartes arrondies disposées en grille 2 colonnes ; la carte survolée ou choisie est cerclée de noir.

## Version 32
- Synthèse de l'agent : contenu v24 inchangé. Retour à une ligne d'analyse horizontale, plus stylée (trait pointillé qui se remplit jusqu'à l'étape affichée, point lumineux orange, grands chiffres) ; rubriques en cartes empilées sur une seule colonne, chacune à sa hauteur (plus de grille).

## Version 33
- **Synthèse & chat de l'agent** : une seule page. La synthèse (parcours, priorités, risques, évolution, recommandations) occupe la zone principale ; le chat (composant `AgentChat.vue`, mêmes appels API qu'avant) est une colonne fixe à droite (tiroir sur écran étroit) avec effets IA : orbe animé, bordure lumineuse pendant la réflexion, étapes d'analyse, écriture progressive des réponses. Boutons « Demander à l'agent » sur les risques et recommandations. L'ancienne page `/chat` redirige vers `/situation`.
- **Détails sur la tâche** (ex-Analyse de tâche) : bloc Recommandations retiré (le traitement reste dans la synthèse), bandeau discret indiquant s'il existe des recommandations avec lien vers la synthèse, description mise en valeur ; l'analyse (situation / prévision), la modification d'échéance et la chronologie sont conservées.
- **Tableau de bord** : cartes élevées, KPI avec part des tickets, repères du projet (échéance finale, prochaine échéance, retards, tickets sans membre), colonne d'avancement dans la liste. Aucune logique modifiée.

## Version 34 · « Cockpit IA »
- **Tableau de bord** : jauge de santé en demi-cercle (arcs par situation, aiguille, survol lié à la légende), quatre indicateurs cliquables (filtres), bande de répartition, repères du projet, **frise des 14 prochains jours** (une pastille par ticket, colonne « Retard »), avancement avec repères 25/50/75 %, charge par membre avec badge de niveau. Données et filtres inchangés.
- **Détails sur la tâche** : rail du cycle de vie dans l'en-tête, description en grand format avec rappel des faits, analyse de l'agent en console lumineuse (situation / prévision) avec accès à la synthèse, colonne de droite (échéance + chronologie).
- **Synthèse & chat** : nouvelle zone « Synthèse de l'agent » mise en avant (texte de la synthèse, chiffres du projet, questions rapides vers le chat). Le reste de la page et le chat sont inchangés. Aucun appel API modifié.


## Révision 38 (corrections)
- **Tableau des tickets** : même espace (2,5 rem) entre tous les contenus ; colonnes statut/échéance au plus près du contenu, avancement extensible, « Détails » aligné à droite ; avatars lisibles.
- **Choix du projet** : projets classés du plus récent au plus ancien.
- **E-mails** : voir `CONSIGNE_EMAIL.md` (configuration Gmail, diagnostic) ; bascule automatique SSL ⇄ STARTTLS et erreur détaillée par étape.


## Notes de version v18 (audit CDC v10)

**Clôture** : atteindre 100 % d'avancement ne ferme plus le ticket (statut et avancement sont indépendants). Seul le haut responsable valide la clôture (bouton « Valider la clôture » dans le détail du ticket → `POST /tickets/{id}/cloture` → CRM `PUT /tickets/{id}/cloture`, clé de service). Le CRM refuse `statut=ferme` par la voie équipe (409).

**Critères d'acceptation** : générés par le LLM à partir du cahier des charges, validés en Python (rejet des critères génériques, sans lien avec le document ou contenant des chiffres absents du texte), stockés (`taches.criteres_acceptation`, `tickets.criteres_acceptation` côté CRM), modifiables à la relecture, affichés dans le détail du ticket et le cahier du projet. Si le document est insuffisant : aucun critère et une ambiguïté signalée.

**Migration SQL** : `scripts/migration_criteres_acceptation.sql` (le CRM l'applique aussi automatiquement au démarrage).

**Sécurité** : verrouillage des tentatives de connexion (429), longueurs max, en-têtes de sécurité, CORS restreint, garde-fou `APP_ENV=production` (refus des secrets par défaut), comparaison de la clé de service à temps constant. Résiduel : les routes « équipe » du CRM simulateur restent sans authentification (à isoler réseau).

**Ollama local** : dans `Backend_AgentIA/.env` : `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=llama3.1:8b`, `LLM_API_KEY=` vide. Puis `ollama pull llama3.1:8b` et `ollama serve`. Test : Administration → test du LLM. Groq reste utilisable en changeant ces trois variables. Le serveur doit tourner avec le fuseau local (`TZ`) pour la bascule de 17 h.

**Tests** : `cd Backend_AgentIA && python -m pytest tests -q` (51) ; CRM : `CRM_DATABASE_URL=...arato_crm_test python -m pytest tests -q` (6). `tests/fake_ollama.py` simule l'API Ollama (ce n'est pas un modèle).

## Notes de version v19

- **Critères d'acceptation toujours proposés** : le modèle en rédige 2 à 4 ; s'il n'en propose aucun de recevable (document peu détaillé, modèle indisponible) ou pour un ticket ancien, 1 à 3 critères par défaut sont déduits de l'énoncé de la tâche (sans chiffre ni fait inventé) et signalés « à affiner ». Le message « Aucun critère » n'existe plus.
- **Clôture conditionnée** : la section « Clôturer la tâche » n'apparaît que si l'avancement CRM est à 100 % ET que tous les critères sont cochés. Les cases se cochent dans le détail du ticket (`PUT /tickets/{id}/criteres/{n}/validation`). Le serveur refuse la clôture (409) si l'une des deux conditions manque.
- **Chat** : nouveaux outils (critères d'un ticket, recherche par titre, tâches d'un membre, vue d'ensemble), règles métier dans le prompt, routage moins restrictif (les questions sur les critères, la clôture ou un membre ne sont plus jugées « hors champ »), repli sans modèle étendu.
- **Base de données** : nouvelle table `validations_criteres` (`scripts/migration_validations_criteres.sql`, créée aussi automatiquement au démarrage). Aucune colonne existante modifiée ; pas de migration côté CRM.

## Notes de version v19.1

- **Import du cahier** : l'analyse est portée par un store (`stores/analyse.ts`) : quitter puis revenir sur la page ne l'interrompt pas, et l'historique affiche une ligne « Analyse en cours ». Le résultat (ou l'erreur) est repris au retour et l'historique rechargé.
- **Chronologie du ticket** : filtres Tout / Statuts / Avancements / Mises en attente / Retards (comptages exacts), tri récent↔ancien, message adapté quand un filtre est vide.
- **Chat** : répond aux questions sur les tâches/projet déjà fermés (« projet terminé »), distingue ce qui est déjà clôturé de ce qui est clôturable ; le libellé de repli distingue « modèle indisponible » et « réponse du modèle non vérifiée » ; comptages simples tolérés dans la vérification des chiffres.

## Notes de version v19.2

- **Synthèse – onglet Évolution** : le type de chaque évolution est lu sur les phrases exactes produites par le programme (ajouts, statuts, avancements, retards et alertes, échéances, motifs, autres) ; filtres avec comptages exacts ; retour automatique à « Tout » si le type choisi se vide ; « Voir plus » et « Afficher tout (N) » suivent le filtre.

## Notes de version v19.3

- **Chat (repli sans modèle)** : réponses directes aux questions sur les tâches en attente (« Oui, N tâche(s)… / Non, aucune… » avec motif et membre), les comptages, les statuts (nouveau / ouvert / en cours), les échéances et l'avancement. Une question non reconnue n'est plus remplacée par le rapport général : l'agent demande de reformuler.

## Notes de version v19.4

- **Tâches répétitives** : à la génération, les tâches qui couvrent la même exigence (titres quasi identiques, mêmes mots clés, même passage du document) sont fusionnées avant la numérotation (durée la plus longue conservée, dépendances redirigées) et signalées dans les ambiguïtés. Les prompts imposent « une exigence = une tâche ».
- **Chat** : réponses ciblées sur une tâche (description, dépendances, responsable, échéance, statut), liste de toutes les tâches, et consigne « rester strictement sur la question » pour le modèle.
