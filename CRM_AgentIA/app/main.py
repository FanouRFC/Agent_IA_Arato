"""API du CRM d'Arato (périmètre : échanges avec l'agent IA et suivi des tâches). Swagger : /docs"""
import datetime as dt
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (Base, Evenement, HistoriqueAvancement, HistoriqueStatut, Membre, Projet, SessionLocal, Ticket,
                     engine)

SERVICE_KEY = settings.crm_service_key
STATUTS = ["nouveau", "ouvert", "en_cours", "en_attente", "ferme"]
MOTIFS_ATTENTE = ["attente d'une information", "attente d'une validation", "problème technique",
                  "dépendance non terminée", "information manquante", "autre"]
AVANCEMENTS = (0, 25, 50, 75, 100)

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="CRM Arato – API pour l'agent IA", version="1.0", lifespan=lifespan)


def get_db():
    with SessionLocal() as db:
        yield db


def service_only(x_service_key: Optional[str] = Header(None)):
    """Échéance et est_en_retard : écriture réservée à l'application (connecteur)."""
    if x_service_key != SERVICE_KEY:
        raise HTTPException(403, "Écriture réservée à l'application (connecteur)")


def _ticket(db: Session, tid: int) -> Ticket:
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404, "Ticket introuvable")
    return t


def _check_member(t: Ticket, auteur_id: int):
    if auteur_id not in [m.id for m in t.membres]:
        raise HTTPException(403, "Seul un membre rattaché au ticket peut effectuer cette action")


def _event(db, t, type_, detail="", source="crm"):
    db.add(Evenement(ticket_id=t.id, type=type_, detail=detail, source=source))


def out(t: Ticket) -> dict:
    return {
        "id": t.id, "titre": t.titre, "description": t.description, "statut": t.statut,
        "avancement_declare": t.avancement_declare, "date_creation": t.date_creation, "echeance": t.echeance,
        "est_en_retard": t.est_en_retard, "date_fermeture": t.date_fermeture, "projet_id": t.projet_id,
        "membre_ids": [m.id for m in t.membres], "depend_de_ids": [d.id for d in t.depend_de],
        "motif_attente_courant": t.motif_attente_courant, "motif_retard_courant": t.motif_retard_courant,
    }


# ---------- Schémas ----------
class TicketCreate(BaseModel):
    titre: str
    description: str = ""
    projet_id: int
    echeance: dt.date
    membre_ids: list[int] = []
    depend_de_ids: list[int] = []
    date_creation: Optional[dt.date] = None


class StatutIn(BaseModel):
    statut: str
    auteur_id: int
    categorie: Optional[str] = Field(None, description="Obligatoire pour « en_attente »")
    motif: Optional[str] = None


class AvancementIn(BaseModel):
    avancement: int
    auteur_id: int


class MotifRetardIn(BaseModel):
    motif: str
    auteur_id: int


class EcheanceIn(BaseModel):
    echeance: dt.date


class RetardIn(BaseModel):
    valeur: bool


# ---------- Création / consultation ----------
@app.post("/tickets", dependencies=[Depends(service_only)], status_code=201)
def creer_ticket(b: TicketCreate, db: Session = Depends(get_db)):
    """Statut « nouveau », avancement 0 %, est_en_retard faux, échéance fournie."""
    if not db.get(Projet, b.projet_id):
        raise HTTPException(404, "Projet introuvable")
    t = Ticket(titre=b.titre, description=b.description, projet_id=b.projet_id, echeance=b.echeance,
               date_creation=b.date_creation or dt.date.today(), statut="nouveau", avancement_declare=0,
               est_en_retard=False)
    t.membres = [m for m in (db.get(Membre, i) for i in b.membre_ids) if m]
    t.depend_de = [d for d in (db.get(Ticket, i) for i in b.depend_de_ids) if d]
    db.add(t)
    db.flush()
    db.add(HistoriqueStatut(ticket_id=t.id, statut="nouveau"))
    _event(db, t, "creation", source="service")
    db.commit()
    return out(t)


@app.get("/tickets")
def lister_tickets(statut: Optional[str] = None, projet_id: Optional[int] = None, membre_id: Optional[int] = None,
                   anciennete_jours: Optional[int] = Query(None, description="Créés depuis au moins N jours"),
                   db: Session = Depends(get_db)):
    q = select(Ticket).order_by(Ticket.id)
    if statut:
        q = q.where(Ticket.statut == statut)
    if projet_id:
        q = q.where(Ticket.projet_id == projet_id)
    if anciennete_jours is not None:
        q = q.where(Ticket.date_creation <= dt.date.today() - dt.timedelta(days=anciennete_jours))
    res = db.scalars(q).all()
    if membre_id:
        res = [t for t in res if membre_id in [m.id for m in t.membres]]
    return [out(t) for t in res]


@app.get("/tickets/{tid}")
def lire_ticket(tid: int, db: Session = Depends(get_db)):
    return out(_ticket(db, tid))


@app.get("/tickets/{tid}/membres")
def membres_du_ticket(tid: int, db: Session = Depends(get_db)):
    return [{"id": m.id, "nom": m.nom, "profil": m.profil, "email": m.email} for m in _ticket(db, tid).membres]


@app.get("/tickets/{tid}/historique")
def historique(tid: int, db: Session = Depends(get_db)):
    """Statuts, motifs d'attente et de retard successifs, avancements. Jamais écrasés."""
    _ticket(db, tid)
    hs = db.scalars(select(HistoriqueStatut).where(HistoriqueStatut.ticket_id == tid)
                    .order_by(HistoriqueStatut.date, HistoriqueStatut.id)).all()
    ha = db.scalars(select(HistoriqueAvancement).where(HistoriqueAvancement.ticket_id == tid)
                    .order_by(HistoriqueAvancement.date)).all()
    return {
        "statuts": [{"date": h.date, "statut": h.statut, "type_motif": h.type_motif, "categorie": h.categorie,
                     "motif": h.motif, "auteur_id": h.auteur_id, "date_resolution": h.date_resolution} for h in hs],
        "avancements": [{"date": a.date, "ancienne": a.ancienne, "nouvelle": a.nouvelle, "auteur_id": a.auteur_id}
                        for a in ha],
    }


# ---------- Écritures par l'équipe (membres) ----------
@app.put("/tickets/{tid}/statut")
def maj_statut(tid: int, b: StatutIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    _check_member(t, b.auteur_id)
    if b.statut not in STATUTS:
        raise HTTPException(422, "Statut inconnu")
    if b.statut == t.statut:
        raise HTTPException(409, "Le ticket a déjà ce statut")
    if b.statut == "en_attente":
        if b.categorie not in MOTIFS_ATTENTE:
            raise HTTPException(422, "Motif d'attente obligatoire : " + ", ".join(MOTIFS_ATTENTE))
        if b.categorie == "autre" and not b.motif:
            raise HTTPException(422, "Précisez le motif (texte libre)")
    now = dt.datetime.now()
    # Archivage : les motifs en cours sont clôturés (date de résolution), jamais effacés
    for h in db.scalars(select(HistoriqueStatut).where(
            HistoriqueStatut.ticket_id == tid, HistoriqueStatut.type_motif.is_not(None),
            HistoriqueStatut.date_resolution.is_(None))):
        h.date_resolution = now
    t.motif_attente_courant = None
    t.motif_retard_courant = None
    t.statut = b.statut
    t.date_fermeture = now.date() if b.statut == "ferme" else None
    db.add(HistoriqueStatut(ticket_id=tid, statut=b.statut, auteur_id=b.auteur_id, date=now))
    if b.statut == "en_attente":
        texte = b.motif or b.categorie
        t.motif_attente_courant = texte
        db.add(HistoriqueStatut(ticket_id=tid, statut="en_attente", type_motif="attente", categorie=b.categorie,
                                motif=texte, auteur_id=b.auteur_id, date=now))
    _event(db, t, "changement_statut", b.statut)
    db.commit()
    return out(t)


@app.put("/tickets/{tid}/avancement")
def maj_avancement(tid: int, b: AvancementIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    _check_member(t, b.auteur_id)
    if b.avancement not in AVANCEMENTS:
        raise HTTPException(422, "Avancement autorisé : 0, 25, 50, 75 ou 100")
    db.add(HistoriqueAvancement(ticket_id=tid, ancienne=t.avancement_declare, nouvelle=b.avancement,
                                auteur_id=b.auteur_id))
    _event(db, t, "modification_avancement", f"{t.avancement_declare}->{b.avancement}")
    t.avancement_declare = b.avancement  # la dernière valeur saisie fait foi
    db.commit()
    return out(t)


@app.put("/tickets/{tid}/motif-retard")
def motif_retard(tid: int, b: MotifRetardIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    _check_member(t, b.auteur_id)
    if t.statut not in ("ouvert", "en_cours"):
        raise HTTPException(409, "Motif de retard : tickets « ouvert » ou « en cours » uniquement")
    if t.motif_retard_courant:
        raise HTTPException(409, "Motif déjà saisi")
    t.motif_retard_courant = b.motif
    db.add(HistoriqueStatut(ticket_id=tid, statut=t.statut, type_motif="retard", motif=b.motif,
                            auteur_id=b.auteur_id))
    _event(db, t, "motif_retard", b.motif)
    db.commit()
    return out(t)


# ---------- Écritures réservées à l'application (connecteur) ----------
@app.put("/tickets/{tid}/echeance", dependencies=[Depends(service_only)])
def maj_echeance(tid: int, b: EcheanceIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    t.echeance = b.echeance
    _event(db, t, "modification_echeance", str(b.echeance), source="service")
    db.commit()
    return out(t)


@app.put("/tickets/{tid}/est-en-retard", dependencies=[Depends(service_only)])
def maj_retard(tid: int, b: RetardIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    t.est_en_retard = b.valeur
    _event(db, t, "indicateur_retard", str(b.valeur), source="service")
    db.commit()
    return out(t)


# ---------- Référentiels et flux d'événements ----------
@app.get("/membres")
def membres(db: Session = Depends(get_db)):
    return [{"id": m.id, "nom": m.nom, "profil": m.profil, "email": m.email} for m in db.scalars(select(Membre))]


@app.get("/profils")
def profils(db: Session = Depends(get_db)):
    return sorted({m.profil for m in db.scalars(select(Membre))})


@app.get("/projets")
def projets(db: Session = Depends(get_db)):
    return [{"id": p.id, "nom": p.nom} for p in db.scalars(select(Projet))]


@app.get("/evenements")
def evenements(since_id: int = 0, db: Session = Depends(get_db)):
    """Journal des changements pertinents, lu par le connecteur."""
    ev = db.scalars(select(Evenement).where(Evenement.id > since_id).order_by(Evenement.id).limit(500)).all()
    return [{"id": e.id, "ticket_id": e.ticket_id, "type": e.type, "detail": e.detail, "source": e.source,
             "date": e.date} for e in ev]
