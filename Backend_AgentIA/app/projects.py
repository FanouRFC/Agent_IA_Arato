"""Organisation par projet (2.6) : un cahier des charges validé = un projet = un contexte distinct pour l'agent.
Les projets de l'application sont synchronisés avec ceux du CRM ; la clé de rattachement est crm_projet_id."""
import logging
import threading
import unicodedata

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .connector import connector as crm
from .models import (AnalyseTicket, CahierDesCharges, ConversationChat, JournalAction, Notification, Projet, Rapport,
                     Recommandation, SuiviRetard, SyntheseSuivi)

log = logging.getLogger("projets")
_purge_lock = threading.Lock()


# ---------- Unicité du nom de projet ----------
def nom_propre(nom: str) -> str:
    """Nom tel qu'il est enregistré : espaces superflus retirés (« Mon   projet » → « Mon projet »)."""
    return " ".join((nom or "").split())


def cle_nom(nom: str) -> str:
    """Clé de comparaison : sans accents, sans majuscules, sans espaces superflus. « EZAKA », « ezaka » et « Ézaka »
    désignent donc le même projet (aucun doublon possible par simple changement de casse ou d'accent)."""
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", nom_propre(nom)) if not unicodedata.combining(c))
    return sans_accent.casefold()


def nom_existant(db: Session, nom: str) -> str | None:
    """Nom du projet existant (application ou CRM) qui porte déjà ce nom, ou None."""
    cle = cle_nom(nom)
    for (n,) in db.execute(select(Projet.nom)):
        if cle_nom(n) == cle:
            return n
    try:
        for p in crm.projets():
            if cle_nom(p["nom"]) == cle:
                return p["nom"]
    except Exception as e:        # CRM momentanément injoignable : la base de l'application (synchronisée) fait foi
        log.warning("Contrôle du nom dans le CRM impossible : %s", e)
    return None


def verifier_nom_unique(db: Session, nom: str) -> str:
    """Refuse (409) un nom déjà pris ; retourne le nom nettoyé. Appelé au dépôt du cahier ET à la validation."""
    propre = nom_propre(nom)
    deja = nom_existant(db, propre)
    if deja is not None:
        raise HTTPException(409, f"Un projet nommé « {deja} » existe déjà. Choisissez un autre nom de projet.")
    return propre


def purge(db: Session, projet: Projet, auteur: str = "système") -> None:
    """Projet supprimé dans le CRM : on supprime aussi, ici, tout ce qui le concerne (suivi, synthèses, recommandations,
    conversations, rapports, cahier des charges et notifications). Les tickets ont déjà disparu du CRM, en cascade."""
    nom, pid = projet.nom, projet.id
    with _purge_lock:                                  # le flux d'événements et la synchronisation peuvent arriver ensemble
        if db.scalar(select(Projet.id).where(Projet.id == pid)) is None:
            return
        _purger(db, projet, nom, pid, auteur)


def _purger(db: Session, projet: Projet, nom: str, pid: int, auteur: str) -> None:
    cahiers = list(db.scalars(select(CahierDesCharges).where(CahierDesCharges.projet_id == pid)))
    ids_taches = [t.id for c in cahiers for t in c.taches]
    if ids_taches:
        db.execute(delete(Notification).where(Notification.id_tache.in_(ids_taches)))
    for c in cahiers:
        db.delete(c)                                   # ses tâches suivent (cascade)
    db.flush()
    for modele in (AnalyseTicket, SuiviRetard, SyntheseSuivi, Recommandation, ConversationChat, Rapport):
        db.execute(delete(modele).where(modele.id_projet == pid))
    db.delete(projet)
    db.add(JournalAction(action=f"Projet « {nom} » supprimé dans le CRM : données de suivi supprimées", auteur=auteur))
    db.commit()


def sync(db: Session) -> list[Projet]:
    """Crée/met à jour les projets de l'application à partir des projets du CRM (échec du CRM toléré),
    et supprime ceux qui n'existent plus dans le CRM."""
    try:
        distants = crm.projets()
        reponse_ok = True
    except Exception as e:
        log.warning("Projets du CRM indisponibles : %s", e)
        distants, reponse_ok = [], False
    connus = {p.crm_projet_id: p for p in db.scalars(select(Projet))}
    if reponse_ok:
        presents = {d["id"] for d in distants}
        for cid, p in list(connus.items()):
            if cid is not None and cid not in presents:
                purge(db, p)
                del connus[cid]
    for d in distants:
        p = connus.get(d["id"])
        if not p:
            db.add(Projet(nom=d["nom"], crm_projet_id=d["id"], statut="actif"))
        elif p.nom != d["nom"]:
            p.nom = d["nom"]
    db.commit()
    return list(db.scalars(select(Projet).where(Projet.crm_projet_id.is_not(None)).order_by(Projet.id.desc())))   # du plus récent au plus ancien


def get_or_create_for_crm(db: Session, crm_id: int, nom: str) -> Projet:
    p = db.scalars(select(Projet).where(Projet.crm_projet_id == crm_id)).first()
    if not p:
        p = Projet(nom=nom, crm_projet_id=crm_id, statut="actif")
        db.add(p)
        db.commit()
    return p


def get(db: Session, pid: int) -> Projet:
    p = db.get(Projet, pid)
    if not p or p.crm_projet_id is None:
        raise HTTPException(404, "Projet introuvable")
    return p


def of_ticket(db: Session, ticket: dict) -> Projet:
    p = db.scalars(select(Projet).where(Projet.crm_projet_id == ticket["projet_id"])).first()
    return p or get_or_create_for_crm(db, ticket["projet_id"], f"Projet {ticket['projet_id']}")
