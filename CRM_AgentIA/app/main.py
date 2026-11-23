"""API du CRM d'Arato (périmètre : échanges avec l'agent IA et suivi des tâches). Swagger : /docs"""
import datetime as dt
from contextlib import asynccontextmanager
from typing import Optional
import hmac
import logging
from sqlalchemy import delete, func, select

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import media
from .config import settings
from .models import (Base, Evenement, HistoriqueAvancement, HistoriqueStatut, Membre, Projet, SessionLocal, Ticket,
                     engine, ticket_deps, ticket_membres)

SERVICE_KEY = settings.crm_service_key
STATUTS = ["nouveau", "ouvert", "en_cours", "en_attente", "ferme"]
MOTIFS_ATTENTE = ["attente d'une information", "attente d'une validation", "problème technique",
                  "dépendance non terminée", "information manquante", "autre"]
AVANCEMENTS = (0, 25, 50, 75, 100)
# L'avancement ne se modifie que sur un ticket en travail. Atteindre 100 % ne change JAMAIS le statut : la clôture est une
# décision humaine, validée par le haut responsable via l'application (PUT /tickets/{id}/cloture, clé de service).
STATUTS_AVANCEMENT = ("ouvert", "en_cours")
log = logging.getLogger("crm")

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    migrer()
    if SERVICE_KEY in ("", "change-me-service-key"):
        log.warning("CRM_SERVICE_KEY par défaut (ou vide) : changez-la dans .env (elle protège l'échéance, est_en_retard, la clôture).")
    yield


app = FastAPI(title="CRM Arato – API pour l'agent IA", version="1.0", lifespan=lifespan)


def get_db():
    with SessionLocal() as db:
        yield db


def migrer():
    """Mise à jour d'une base existante (idempotente, aucune donnée supprimée) : colonne des critères d'acceptation."""
    from sqlalchemy import inspect, text
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    if "tickets" in insp.get_table_names() and "criteres_acceptation" not in {c["name"] for c in insp.get_columns("tickets")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tickets ADD COLUMN criteres_acceptation JSON"))


def service_only(x_service_key: Optional[str] = Header(None)):
    """Échéance, est_en_retard et clôture : écriture réservée à l'application (connecteur). Comparaison en temps constant ;
    une clé de service vide ne laisse jamais passer une requête sans en-tête."""
    if not SERVICE_KEY or not x_service_key or not hmac.compare_digest(x_service_key.encode(), SERVICE_KEY.encode()):
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
    db.add(Evenement(ticket_id=t.id, projet_id=t.projet_id, type=type_, detail=detail, source=source))


def out(t: Ticket) -> dict:
    return {
        "id": t.id, "titre": t.titre, "description": t.description, "statut": t.statut,
        "avancement_declare": t.avancement_declare, "date_creation": t.date_creation, "echeance": t.echeance,
        "est_en_retard": t.est_en_retard, "date_fermeture": t.date_fermeture, "projet_id": t.projet_id,
        "membre_ids": [m.id for m in t.membres], "depend_de_ids": [d.id for d in t.depend_de],
        "motif_attente_courant": t.motif_attente_courant, "motif_retard_courant": t.motif_retard_courant,
        "criteres_acceptation": list(t.criteres_acceptation or []),
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
    criteres_acceptation: list[str] = Field(default_factory=list, max_length=12)   # critères vérifiables (générés puis relus par le responsable)

    @field_validator("criteres_acceptation")
    @classmethod
    def _criteres(cls, v):
        propres = [" ".join(str(x).split()) for x in v]
        if any(len(x) > 400 for x in propres):
            raise ValueError("Un critère d'acceptation ne dépasse pas 400 caractères")
        return [x for x in propres if x]


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
def creer_ticket(b: TicketCreate, db: Session = Depends(get_db), source: str = "service"):
    """Statut « nouveau », avancement 0 %, est_en_retard faux, échéance fournie."""
    if not db.get(Projet, b.projet_id):
        raise HTTPException(404, "Projet introuvable")
    t = Ticket(titre=b.titre, description=b.description, projet_id=b.projet_id, echeance=b.echeance,
               date_creation=b.date_creation or dt.date.today(), statut="nouveau", avancement_declare=0,
               est_en_retard=False, criteres_acceptation=b.criteres_acceptation)
    t.membres = [m for m in (db.get(Membre, i) for i in b.membre_ids) if m]
    t.depend_de = [d for d in (db.get(Ticket, i) for i in b.depend_de_ids) if d]
    if any(d.projet_id != b.projet_id for d in t.depend_de):
        raise HTTPException(422, "Une dépendance doit appartenir au même projet")
    db.add(t)
    db.flush()
    db.add(HistoriqueStatut(ticket_id=t.id, statut="nouveau"))
    _event(db, t, "creation", source=source)
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


def membre_out(m: Membre, actives: Optional[list[int]] = None) -> dict:
    """Fiche d'un membre ; `photo` est un chemin relatif du CRM (avec version pour le cache), null sans photo."""
    v = media.version(f"membre_{m.id}")
    out_ = {"id": m.id, "nom": m.nom, "profil": m.profil, "email": m.email,
            "photo": f"/membres/{m.id}/photo?v={v}" if v else None}
    if actives is not None:
        out_["taches_actives"] = actives
    return out_


def _taches_actives(db: Session) -> dict[int, list[int]]:
    """Tickets non fermés rattachés à chaque membre. Un projet dont tous les tickets sont fermés est clôturé :
    ses membres sont libres (ses tickets n'apparaissent donc jamais ici)."""
    res: dict[int, list[int]] = {}
    q = (select(ticket_membres.c.membre_id, Ticket.id).join(Ticket, Ticket.id == ticket_membres.c.ticket_id)
         .where(Ticket.statut != "ferme").order_by(Ticket.id))
    for mid, tid_ in db.execute(q):
        res.setdefault(mid, []).append(tid_)
    return res


def _projets_actifs_du_membre(db: Session, ids: list[int]) -> str:
    if not ids:
        return ""
    noms = db.scalars(select(Projet.nom).join(Ticket, Ticket.projet_id == Projet.id).where(Ticket.id.in_(ids)).distinct()).all()
    return ", ".join(f"« {n} »" for n in noms)


@app.get("/tickets/{tid}/membres")
def membres_du_ticket(tid: int, db: Session = Depends(get_db)):
    return [membre_out(m) for m in _ticket(db, tid).membres]


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
    if b.statut == "ferme":
        raise HTTPException(409, "La clôture d'un ticket est validée par le haut responsable (espace « Agent IA ») : "
                                 "elle ne se choisit pas ici, même à 100 % d'avancement.")
    if t.statut == "ferme":
        raise HTTPException(409, "Ticket fermé : son statut n'est plus modifiable")
    nb = len(t.membres)
    if b.statut == "ouvert" and nb < 2:
        raise HTTPException(422, "Un ticket « ouvert » est rattaché à plusieurs personnes (rattachez d'abord d'autres membres)")
    if b.statut == "en_cours" and nb != 1:
        raise HTTPException(422, "Un ticket « en cours » est rattaché à une personne précise (ajustez les membres rattachés)")
    if b.statut == "en_attente":
        if b.categorie not in MOTIFS_ATTENTE:
            raise HTTPException(422, "Motif d'attente obligatoire : " + ", ".join(MOTIFS_ATTENTE))
        if b.categorie == "autre" and not b.motif:
            raise HTTPException(422, "Précisez le motif (texte libre)")
    _appliquer_statut(db, t, b.statut, b.auteur_id, b.categorie, b.motif)
    db.commit()
    return out(t)


def _appliquer_statut(db: Session, t: Ticket, statut: str, auteur_id: Optional[int], categorie: Optional[str] = None,
                      motif: Optional[str] = None, source: str = "crm"):
    """Changement de statut + historique + événement (changement par l'équipe, ou clôture validée par le haut responsable)."""
    now = dt.datetime.now()
    # Archivage : les motifs en cours sont clôturés (date de résolution), jamais effacés
    for h in db.scalars(select(HistoriqueStatut).where(
            HistoriqueStatut.ticket_id == t.id, HistoriqueStatut.type_motif.is_not(None),
            HistoriqueStatut.date_resolution.is_(None))):
        h.date_resolution = now
    t.motif_attente_courant = None
    t.motif_retard_courant = None
    t.statut = statut
    t.date_fermeture = now.date() if statut == "ferme" else None
    db.add(HistoriqueStatut(ticket_id=t.id, statut=statut, auteur_id=auteur_id, date=now))
    if statut == "en_attente":
        texte = motif or categorie
        t.motif_attente_courant = texte
        db.add(HistoriqueStatut(ticket_id=t.id, statut="en_attente", type_motif="attente", categorie=categorie,
                                motif=texte, auteur_id=auteur_id, date=now))
    _event(db, t, "changement_statut", statut, source=source)


@app.put("/tickets/{tid}/avancement")
def maj_avancement(tid: int, b: AvancementIn, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    _check_member(t, b.auteur_id)
    if b.avancement not in AVANCEMENTS:
        raise HTTPException(422, "Avancement autorisé : 0, 25, 50, 75 ou 100")
    if t.statut not in STATUTS_AVANCEMENT:
        raise HTTPException(409, "L'avancement ne peut évoluer que pour un ticket « Ouvert » ou « En cours »")
    if b.avancement == t.avancement_declare:
        raise HTTPException(409, "Le ticket a déjà cet avancement")
    db.add(HistoriqueAvancement(ticket_id=tid, ancienne=t.avancement_declare, nouvelle=b.avancement,
                                auteur_id=b.auteur_id))
    _event(db, t, "modification_avancement", f"{t.avancement_declare}->{b.avancement}")
    t.avancement_declare = b.avancement  # la dernière valeur saisie fait foi ; le statut ne change jamais (même à 100 %)
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
    if not t.est_en_retard and str(t.echeance)[:10] >= dt.date.today().isoformat():
        raise HTTPException(409, "Motif de retard : l'échéance n'est pas dépassée")
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


class ClotureIn(BaseModel):
    valide_par: str = Field(min_length=3, max_length=254, description="Compte du haut responsable qui valide la clôture")


@app.put("/tickets/{tid}/cloture", dependencies=[Depends(service_only)])
def cloturer(tid: int, b: ClotureIn, db: Session = Depends(get_db)):
    """Clôture d'un ticket : décision du haut responsable, transmise par l'application (connecteur) UNIQUEMENT.
    Le taux d'avancement et le statut sont indépendants : atteindre 100 % ne ferme rien, seule cette décision ferme."""
    t = _ticket(db, tid)
    if t.statut == "ferme":
        raise HTTPException(409, "Ticket déjà fermé")
    _appliquer_statut(db, t, "ferme", None, source="service")
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
    actives = _taches_actives(db)
    return [membre_out(m, actives.get(m.id, [])) for m in db.scalars(select(Membre).order_by(Membre.id))]


@app.get("/profils")
def profils(db: Session = Depends(get_db)):
    return sorted({m.profil for m in db.scalars(select(Membre))})


def _cle_nom(nom: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", " ".join(nom.split())) if not unicodedata.combining(c)).casefold()


class ProjetIn(BaseModel):
    nom: str = Field(min_length=2, max_length=200)


@app.post("/projets", dependencies=[Depends(service_only)], status_code=201)
def creer_projet(b: ProjetIn, db: Session = Depends(get_db)):
    """Un cahier des charges validé = un projet (créé par l'application après validation du haut responsable)."""
    nom = " ".join(b.nom.split())
    cle = _cle_nom(nom)
    for existant in db.scalars(select(Projet.nom)):          # jamais deux projets de même nom (casse, accents, espaces ignorés)
        if _cle_nom(existant) == cle:
            raise HTTPException(409, f"Un projet nommé « {existant} » existe déjà. Choisissez un autre nom de projet.")
    p = Projet(nom=nom)
    db.add(p)
    db.commit()
    return {"id": p.id, "nom": p.nom}


class MembresIn(BaseModel):
    membre_ids: list[int]


@app.put("/tickets/{tid}/membres")
def maj_membres(tid: int, b: MembresIn, db: Session = Depends(get_db)):
    """Rattachement des membres à un ticket (équipe du CRM)."""
    t = _ticket(db, tid)
    nouveaux = [m for m in (db.get(Membre, i) for i in b.membre_ids) if m]
    if t.statut == "ouvert" and len(nouveaux) < 2:
        raise HTTPException(422, "Un ticket « ouvert » reste rattaché à plusieurs personnes")
    if t.statut == "en_cours" and len(nouveaux) != 1:
        raise HTTPException(422, "Un ticket « en cours » reste rattaché à une personne précise")
    t.membres = nouveaux
    _event(db, t, "changement_membres", ",".join(str(m.id) for m in nouveaux))
    db.commit()
    return out(t)


@app.get("/projets")
def projets(db: Session = Depends(get_db)):
    ouverts = set(db.scalars(select(Ticket.projet_id).where(Ticket.statut != "ferme")))
    return [{"id": p.id, "nom": p.nom, "clos": p.id not in ouverts} for p in db.scalars(select(Projet))]   # clos = tous les tickets fermés


@app.get("/evenements/dernier")
def dernier_evenement(db: Session = Depends(get_db)):
    """Plus grand identifiant d'événement (détecte une réinitialisation du CRM par le backend)."""
    return {"id": db.scalar(select(func.max(Evenement.id))) or 0}


@app.get("/evenements")
def evenements(since_id: int = 0, db: Session = Depends(get_db)):
    """Journal des changements pertinents, lu par le connecteur."""
    ev = db.scalars(select(Evenement).where(Evenement.id > since_id).order_by(Evenement.id).limit(500)).all()
    return [{"id": e.id, "ticket_id": e.ticket_id, "projet_id": e.projet_id, "type": e.type, "detail": e.detail, "source": e.source,
             "date": e.date} for e in ev]


# ---------- Espace équipe : création / modification / suppression depuis le simulateur ----------
@app.post("/equipe/projets", status_code=201)
def equipe_creer_projet(b: ProjetIn, db: Session = Depends(get_db)):
    return creer_projet(b, db)


@app.post("/equipe/tickets", status_code=201)
def equipe_creer_ticket(b: TicketCreate, db: Session = Depends(get_db)):
    """L'échéance est fournie à la création uniquement ; elle reste ensuite en lecture seule."""
    if len(b.titre.strip()) < 2:
        raise HTTPException(422, "Titre trop court")
    return creer_ticket(b, db, source="crm")       # créé par l'équipe : l'agent doit le suivre aussitôt


class MembreIn(BaseModel):
    nom: str = Field(min_length=2, max_length=120)
    profil: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/membres", status_code=201)
def creer_membre(b: MembreIn, db: Session = Depends(get_db)):
    m = Membre(nom=b.nom.strip(), profil=b.profil.strip(), email=b.email.strip())
    db.add(m)
    db.commit()
    return membre_out(m, [])


def _membre(db: Session, mid: int) -> Membre:
    m = db.get(Membre, mid)
    if not m:
        raise HTTPException(404, "Membre introuvable")
    return m


@app.put("/membres/{mid}")
def modifier_membre(mid: int, b: MembreIn, db: Session = Depends(get_db)):
    m = _membre(db, mid)
    m.nom, m.profil, m.email = b.nom.strip(), b.profil.strip(), b.email.strip()
    db.commit()
    return membre_out(m, _taches_actives(db).get(mid, []))


@app.delete("/membres/{mid}")
def supprimer_membre(mid: int, db: Session = Depends(get_db)):
    """Règle de gestion : un membre rattaché à au moins une tâche active (non fermée) ne peut pas être supprimé."""
    m = _membre(db, mid)
    actives = _taches_actives(db).get(mid, [])
    if actives:
        liste = ", ".join(f"T-{i:03d}" for i in actives)
        projets_ = _projets_actifs_du_membre(db, actives)
        raise HTTPException(409, f"Suppression impossible : {m.nom} est rattaché à {len(actives)} tâche(s) active(s) ({liste}) "
                                 f"du ou des projets {projets_}. Retirez-le de ces tâches ou attendez leur fermeture.")
    # Seuls des tickets fermés (projets clôturés) le référencent encore : on le détache d'un coup.
    db.execute(delete(ticket_membres).where(ticket_membres.c.membre_id == mid))
    media.supprimer(f"membre_{mid}")
    db.delete(m)
    db.commit()
    return {"ok": True}


@app.get("/membres/{mid}/photo")
def lire_photo(mid: int):
    p = media.chemin(f"membre_{mid}")
    if not p.exists():
        raise HTTPException(404, "Pas de photo")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/membres/{mid}/photo")
async def envoyer_photo(mid: int, fichier: UploadFile = File(...), db: Session = Depends(get_db)):
    m = _membre(db, mid)
    try:
        media.enregistrer(await fichier.read(media.MAX_BYTES + 1), f"membre_{mid}")
    except media.PhotoInvalide as e:
        raise HTTPException(422, str(e))
    return membre_out(m, _taches_actives(db).get(mid, []))


@app.delete("/membres/{mid}/photo")
def retirer_photo(mid: int, db: Session = Depends(get_db)):
    m = _membre(db, mid)
    media.supprimer(f"membre_{mid}")
    return membre_out(m, _taches_actives(db).get(mid, []))


@app.delete("/projets/{pid}")
def supprimer_projet(pid: int, db: Session = Depends(get_db)):
    """Suppression complète d'un projet : tous ses tickets sont supprimés en cascade (dépendances, rattachements, historiques)."""
    p = db.get(Projet, pid)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    ids = list(db.scalars(select(Ticket.id).where(Ticket.projet_id == pid)))
    if ids:
        db.execute(delete(ticket_deps).where(ticket_deps.c.ticket_id.in_(ids) | ticket_deps.c.depend_de_id.in_(ids)))
        db.execute(delete(ticket_membres).where(ticket_membres.c.ticket_id.in_(ids)))
        db.execute(delete(HistoriqueStatut).where(HistoriqueStatut.ticket_id.in_(ids)))
        db.execute(delete(HistoriqueAvancement).where(HistoriqueAvancement.ticket_id.in_(ids)))
        db.execute(delete(Ticket).where(Ticket.id.in_(ids)))
    db.execute(delete(Evenement).where(Evenement.projet_id == pid))   # le flux ne garde rien d'un projet supprimé
    nom = p.nom
    db.delete(p)
    db.add(Evenement(ticket_id=0, projet_id=pid, type="suppression_projet", detail=nom, source="crm"))
    db.commit()
    return {"ok": True, "tickets_supprimes": len(ids)}


class InfosIn(BaseModel):
    titre: Optional[str] = Field(None, min_length=2, max_length=300)
    description: Optional[str] = None
    depend_de_ids: Optional[list[int]] = None


@app.put("/tickets/{tid}/infos")
def maj_infos(tid: int, b: InfosIn, db: Session = Depends(get_db)):
    """Titre, description et dépendances (ni statut, ni échéance, ni est_en_retard)."""
    t = _ticket(db, tid)
    if b.titre is not None:
        t.titre = b.titre.strip()
    if b.description is not None:
        t.description = b.description
    if b.depend_de_ids is not None:
        deps = [d for d in (db.get(Ticket, i) for i in set(b.depend_de_ids)) if d]
        if any(d.projet_id != t.projet_id for d in deps):
            raise HTTPException(422, "Une dépendance doit appartenir au même projet")
        vus, pile = set(), [d.id for d in deps]
        while pile:                                   # refuse les cycles
            i = pile.pop()
            if i == tid:
                raise HTTPException(422, "Dépendance circulaire refusée")
            if i not in vus:
                vus.add(i)
                pile += [x.id for x in db.get(Ticket, i).depend_de]
        t.depend_de = deps
    _event(db, t, "modification_ticket")
    db.commit()
    return out(t)


@app.delete("/tickets/{tid}")
def supprimer_ticket(tid: int, db: Session = Depends(get_db)):
    t = _ticket(db, tid)
    bloques = [o.id for o in db.scalars(select(Ticket)) if tid in [d.id for d in o.depend_de]]
    if bloques:
        raise HTTPException(409, "Impossible : des tickets en dépendent (" + ", ".join(f"T-{i:03d}" for i in bloques) + ")")
    _event(db, t, "suppression")
    t.membres, t.depend_de = [], []
    for h in (HistoriqueStatut, HistoriqueAvancement):
        db.execute(delete(h).where(h.ticket_id == tid))
    db.delete(t)
    db.commit()
    return {"ok": True}