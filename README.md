# PROJET M2 – Agent IA Arato (intégré à votre modèle)

Ce dossier reprend **votre structure** (`Backend_AgentIA`, `Frontend_AgentIA`) et y intègre le projet complet du cahier
des charges v7. Toutes les versions sont **figées sur celles de votre PC** pour éviter tout écart.

```
PROJET M2/
├─ Backend_AgentIA/     FastAPI : agent IA, outils déterministes, connecteur, scheduler, e-mails, rapports
│   ├─ app/  requirements.txt (versions exactes)  requirements-dev.txt  .env.example
├─ CRM_AgentIA/         API du CRM (port 8001) – utilise le MÊME venv que le backend
├─ Frontend_AgentIA/    Vue 3 + TypeScript + Tailwind 4 (votre modèle create-vue : alias @, Pinia, vue-router 5)
├─ scripts/             setup_db.sql, verifier_versions.py, smtp_debug.py
└─ lancer_*.bat  initialiser_crm.bat
```

## Versions de référence (lues dans votre venv et votre node_modules)

| Python 3.13 (venv) | | Frontend (package.json / lock inchangés) | |
|---|---|---|---|
| FastAPI | 0.142.2 | Vue | 3.5.43 |
| Starlette | 1.7.0 | Vue Router | 5.3.1 |
| SQLAlchemy | 2.1.2 | Pinia | 4.0.3 |
| Pydantic | 2.13.5 | Vite | 8.3.2 |
| psycopg2-binary | 2.9.13 | TypeScript | 6.0.3 |
| Uvicorn | 0.54.0 | Tailwind CSS | 4.3.3 |
| python-multipart | 0.0.32 | Node | ^22.18 ou ≥ 24.12 |

Les nouvelles bibliothèques (apscheduler, fastapi-mail, pypdf, python-docx, reportlab, openpyxl, pydantic-settings, pyjwt, httpx)
sont **épinglées en version exacte**, dépendances indirectes comprises : `pip install -r requirements.txt` reproduit donc
le même environnement sur n'importe quel PC. Contrôle : `python ..\scripts\verifier_versions.py` (venv activé).

## Mise en place sur votre PC (Windows)

1. **Fusionner** ce dossier dans votre `D:\PROJET M2` (remplacer les fichiers existants). Votre `venv` et vos `node_modules`
   ne sont pas touchés : ils ne sont pas dans l'archive.
2. **Supprimer** les fichiers de démonstration devenus inutiles dans `Frontend_AgentIA\src` :
   `components\HelloWorld.vue TheWelcome.vue WelcomeItem.vue icons\`, `stores\counter.ts`,
   `views\HomeView.vue AboutView.vue`, `assets\base.css logo.svg`.
3. **PostgreSQL** (installé localement) : `psql -U postgres -f scripts\setup_db.sql`
4. **Python** : dans `Backend_AgentIA` :
   ```
   venv\Scripts\activate
   pip install -r requirements.txt
   python ..\scripts\verifier_versions.py
   copy .env.example .env
   ```
   Puis `copy .env.example .env` dans `CRM_AgentIA` (la clé `CRM_SERVICE_KEY` doit être identique des deux côtés).
5. **LLM open source** : installer Ollama (https://ollama.com), puis `ollama pull qwen2.5:7b-instruct`.
6. **Frontend** : `cd Frontend_AgentIA` puis `npm install` (inchangé si `node_modules` est déjà à jour).

## Lancement (4 fenêtres)

| Action | Commande |
|---|---|
| Jeu de test du CRM (une fois, réexécutable) | `initialiser_crm.bat` |
| CRM – http://localhost:8001/docs | `lancer_crm.bat` |
| Backend – http://localhost:8000/docs | `lancer_backend.bat` |
| Interface – http://localhost:5173 | `lancer_frontend.bat` |
| E-mails de test (facultatif) | `pip install -r requirements-dev.txt` puis `lancer_smtp_test.bat` |

Connexion : `responsable` / `changeme` (modifiable dans `Backend_AgentIA\.env`).

## Ce qui a été adapté à votre modèle

- **Frontend** : conservé tel quel (`package.json`, `package-lock.json`, `tsconfig*`, alias `@`, `vite.config.ts`, plugin
  vue-devtools). Ajouts : proxy `/api` → backend, `src/router`, `src/stores/auth.ts` (Pinia), `src/services/api.ts`, 7 vues.
  Tailwind 4 : palette déclarée dans `src/assets/main.css` (`@theme`), pas de `tailwind.config.js`.
- **Backend / CRM** : configuration lue depuis `.env` (plus de `set -a`, spécifique à Linux) ; démarrage via *lifespan*
  (FastAPI 0.142) ; le trigger PostgreSQL n'est créé que sous PostgreSQL.

## Vérifié / non vérifié

Vérifié avec vos versions exactes (Python 3.13.13, PostgreSQL 16 réel, Node 22.22) : démarrage CRM + backend, jeu de test,
scheduler (événements CRM et temporels), indicateur `est_en_retard`, décision d'échéance, rapports PDF/Excel, trigger
d'immutabilité de l'échéance initiale, `vue-tsc` + `vite build` sans erreur, proxy Vite → backend.
**Non vérifié** : exécution sous Windows (scripts `.bat`), version Python exacte 3.13.15, qualité des réponses d'un vrai LLM
(testé hors ligne : repli déterministe), dépôt réel d'un cahier des charges (nécessite le LLM).
