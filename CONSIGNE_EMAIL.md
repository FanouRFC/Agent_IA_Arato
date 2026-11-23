# Faire marcher l'envoi d'e-mails (Gmail → fenochoumadone@gmail.com)

Erreur rencontrée :
> E-mail non envoyé à fenochoumadone@gmail.com : le serveur SMTP a fermé la connexion (identifiants refusés, ou chiffrement attendu sur ce port)

**Ce que cela veut dire** : l'application a bien trouvé un serveur, mais celui-ci a raccroché pendant la connexion. Les causes, par ordre de fréquence :
1. `MAIL_SERVER` / `MAIL_PORT` ne correspondent pas à Gmail (par ex. `localhost:1025`, ou `gmail.com` au lieu de `smtp.gmail.com`) ;
2. le chiffrement forcé est faux pour le port (`MAIL_SSL_TLS=true` sur le port 587, ou `MAIL_STARTTLS=true` sur le port 465) ;
3. le mot de passe est le mot de passe habituel du compte Google (Gmail le refuse : il faut un **mot de passe d'application**) ;
4. un antivirus ou un pare-feu coupe la connexion sortante (analyse des e-mails, port 587/465 bloqué).

## Étapes à suivre (une seule fois)

**1. Créer le mot de passe d'application Google** (compte qui ENVOIE les e-mails)
- Ouvrir https://myaccount.google.com/security et activer la **validation en 2 étapes** (obligatoire).
- Ouvrir https://myaccount.google.com/apppasswords, créer un mot de passe nommé « Arato » : Google affiche 16 lettres
  (par ex. `abcd efgh ijkl mnop`). Les espaces sont ignorés par l'application.

**2. Modifier `Backend_AgentIA/.env`** (remplacer toute la section E-MAILS par ceci, sans guillemets, sans espaces autour du `=`) :
```
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=adresse.expediteur@gmail.com
MAIL_PASSWORD=abcdefghijklmnop
MAIL_FROM=adresse.expediteur@gmail.com
```
- `MAIL_USERNAME` et `MAIL_FROM` = le compte Gmail qui possède le mot de passe d'application (Gmail refuse un autre expéditeur).
- Ne PAS écrire `MAIL_STARTTLS` ni `MAIL_SSL_TLS` : le chiffrement est choisi automatiquement (587 → STARTTLS, 465 → SSL).
- Le destinataire (ici fenochoumadone@gmail.com) est l'adresse du membre dans le CRM : elle peut être différente de l'expéditeur.

**3. Redémarrer le backend** : fermer la fenêtre `lancer_backend.bat` puis la relancer (le fichier `.env` est aussi relu à chaque envoi).

**4. Tester** : affecter un ticket à un membre dont l'e-mail est fenochoumadone@gmail.com, puis ouvrir **Administration → Journal**.
- Succès : « remis au serveur smtp.gmail.com:587 ». Vérifier la boîte de réception **et les courriers indésirables**.
- Échec : le journal donne maintenant l'étape exacte (connexion, STARTTLS, authentification…), le mode et le port.

## Si l'erreur persiste
| Message du journal | Action |
|---|---|
| « authentification SMTP refusée » | Mot de passe d'application faux ou expiré : en recréer un ; vérifier `MAIL_USERNAME`. |
| « fermé la connexion (étape : connexion) » | Mauvais serveur/port, ou connexion bloquée : essayer `MAIL_PORT=465`. Désactiver l'analyse des e-mails de l'antivirus (Avast, Kaspersky, ESET…). |
| « fermé la connexion (étape : authentification) » | Mot de passe d'application absent (mot de passe normal utilisé) ou validation en 2 étapes non activée. |
| « serveur SMTP … injoignable » | Pas d'Internet, ou pare-feu : tester dans PowerShell `Test-NetConnection smtp.gmail.com -Port 587` (doit afficher `TcpTestSucceeded : True`). |
| E-mail « archivé » seulement | `MAIL_SERVER` est encore `localhost` : le message n'est pas parti (copie dans `Backend_AgentIA/data/outbox`). |

## Ce qui a été amélioré dans le code (sans changer la logique métier)
- Si le serveur coupe la connexion avec le mode de chiffrement configuré, l'application essaie automatiquement l'autre mode (SSL ⇄ STARTTLS) sur le même port, avant de signaler l'échec.
- Un refus d'identifiants n'est jamais rejoué (pas de blocage de compte).
- Le message d'erreur indique désormais l'étape, le mode et le port.
