import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import projects, service
from .api import public, router
from .config import settings
from .db import SessionLocal, init_db
from .models import User
from .security import hash_password

import threading
from . import tools as T

app = FastAPI()

@app.on_event("startup")
def _prechauffer_ocr():
    threading.Thread(target=T.prechauffer_ocr, daemon=True).start()


logging.basicConfig(level=logging.INFO)
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                            # tables + trigger PostgreSQL
    with SessionLocal() as db:
        if not db.scalars(select(User).where(User.email == settings.admin_email.lower())).first():
            db.add(User(email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password)))
            db.commit()
    try:
        with SessionLocal() as db:
            projects.sync(db)                            # un projet de l'application par projet du CRM
    except Exception as e:
        logging.getLogger("main").warning("Synchronisation des projets reportée : %s", e)
    secrets_par_defaut = (settings.jwt_secret in ("", "change-me") or len(settings.jwt_secret) < 16
                          or settings.admin_password in ("", "changeme") or settings.crm_service_key in ("", "change-me-service-key"))
    if secrets_par_defaut:
        if settings.app_env.lower() == "production":
            raise RuntimeError("APP_ENV=production : JWT_SECRET (16 caractères minimum), ADMIN_PASSWORD et CRM_SERVICE_KEY "
                               "ne doivent pas garder leur valeur par défaut. Modifiez le fichier .env.")
        logging.getLogger("main").warning("Secrets par défaut en service : changez JWT_SECRET, ADMIN_PASSWORD et CRM_SERVICE_KEY dans .env "
                                          "(obligatoire avec APP_ENV=production)")
    # Suivi dynamique 100 % automatique (aucun bouton « Réévaluer ») : ces boucles DÉTECTENT les événements ;
    # l'agent (LLM) n'est appelé que lorsqu'un événement pertinent est détecté, ou pour la première évaluation d'un projet.
    scheduler.add_job(service.poll_crm_events, "interval", seconds=settings.event_poll_seconds, max_instances=1,
                      coalesce=True, id="evenements_crm")
    scheduler.add_job(service.temporal_check, "interval", seconds=settings.temporal_tick_seconds, max_instances=1,
                      coalesce=True, id="evenements_temporels")
    scheduler.add_job(service.auto_evaluate, "interval", seconds=settings.auto_eval_seconds, max_instances=1,
                      coalesce=True, id="evaluation_automatique")
    try:
        from . import mailer, smtp_local
        cfg = mailer.config_defaut()
        smtp_local.demarrer(cfg["server"], int(cfg["port"]))
    except Exception as e:
        logging.getLogger("main").warning("Boîte d'envoi de test non démarrée : %s", e)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Agent IA Arato – analyse des cahiers des charges et suivi intelligent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def en_tetes_de_securite(request, call_next):
    """En-têtes de défense en profondeur sur toutes les réponses de l'API."""
    r = await call_next(request)
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("X-Frame-Options", "DENY")
    r.headers.setdefault("Referrer-Policy", "no-referrer")
    return r
app.include_router(public)
app.include_router(router)
