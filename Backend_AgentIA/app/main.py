import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import service
from .api import public, router
from .config import settings
from .db import SessionLocal, init_db
from .models import User
from .security import hash_password

logging.basicConfig(level=logging.INFO)
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                            # tables + trigger PostgreSQL
    with SessionLocal() as db:
        if not db.scalars(select(User).where(User.nom == settings.admin_username)).first():
            db.add(User(nom=settings.admin_username, password_hash=hash_password(settings.admin_password)))
            db.commit()
    # Suivi dynamique : aucun horaire fixe d'analyse. Ces deux boucles ne font que DÉTECTER les événements ;
    # l'agent (LLM) n'est appelé que lorsqu'un événement pertinent est détecté.
    scheduler.add_job(service.poll_crm_events, "interval", seconds=settings.event_poll_seconds, max_instances=1,
                      coalesce=True, id="evenements_crm")
    scheduler.add_job(service.temporal_check, "interval", seconds=settings.temporal_tick_seconds, max_instances=1,
                      coalesce=True, id="evenements_temporels")
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Agent IA Arato – analyse des cahiers des charges et suivi intelligent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(public)
app.include_router(router)
