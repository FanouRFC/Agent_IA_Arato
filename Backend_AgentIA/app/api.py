import datetime as dt
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Optional
from . import affectation

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from .config import settings
from . import agent, llm, mailer, media, plain, projects, reports, service, settings_store
from . import tools as T
from .calendar_utils import add_bd
from .connector import connector as crm
from .db import get_db
from .models import (AnalyseTicket, CahierDesCharges, ConversationChat, JournalAction, Notification, Projet, Rapport,
                     Recommandation, SuiviRetard, SyntheseSuivi, Tache, User, ValidationCritere)
from .security import _FAUSSE_EMPREINTE, create_token, current_admin, hash_password, limite_connexion, verify_password

log = logging.getLogger(__name__)

public = APIRouter()
router = APIRouter(dependencies=[Depends(current_admin)])


def log_action(db: Session, action: str, auteur: str):
    db.add(JournalAction(action=action, auteur=auteur))
    db.commit()


def _crm_down(e: Exception) -> HTTPException:
    return HTTPException(503, f"CRM indisponible ({type(e).__name__}). Vérifiez que « lancer_crm.bat » est démarré.")


# ---------------- Connexion ----------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MDP_MIN = 8

def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_RE.match(v) or len(v) > 254:
        raise HTTPException(422, "Adresse e-mail invalide.")
    return v


def _mdp(v: str):
    if len(v) < MDP_MIN:
        raise HTTPException(422, f"Le mot de passe doit contenir au moins {MDP_MIN} caractères.")


class Login(BaseModel):
    email: str = Field(max_length=254)
    mot_de_passe: str = Field(max_length=200)


class OubliIn(BaseModel):
    email: str
    mot_de_passe: str = Field(min_length=8)
    confirmation: str


@public.post("/auth/mot-de-passe-oublie")
def mot_de_passe_oublie(b: OubliIn, db: Session = Depends(get_db)):
    email = _email(b.email)
    if b.mot_de_passe != b.confirmation:
        raise HTTPException(400, "Les deux mots de passe ne correspondent pas.")
    u = db.scalars(select(User).where(User.email == email)).first()
    if not u or u.statut != "accepte":
        raise HTTPException(404, "Aucun compte accepté avec cet e-mail.")
    u.password_hash = hash_password(b.mot_de_passe)
    db.commit()
    log_action(db, f"Mot de passe réinitialisé : {email}", email)
    return {"ok": True}


@public.post("/auth/login")
def login(b: Login, request: Request, db: Session = Depends(get_db)):
    cle = f"{request.client.host if request.client else '?'}|{b.email.strip().lower()}"
    limite_connexion.verifier(cle)                       # 429 après trop d'échecs consécutifs
    u = db.scalars(select(User).where(User.email == b.email.strip().lower())).first()
    ok = verify_password(b.mot_de_passe, u.password_hash if u else _FAUSSE_EMPREINTE)
    if u and ok and u.statut == "en_attente":
        raise HTTPException(403, "Votre demande d'inscription est en attente de validation par un responsable.")
    if not u or not u.actif or not ok:
        limite_connexion.echec(cle)
        raise HTTPException(401, "E-mail ou mot de passe incorrect")
    limite_connexion.succes(cle)
    return {"token": create_token(u.email), "email": u.email}


# ---------------- Inscription publique (compte créé DÉSACTIVÉ, à valider par un responsable) ----------------
_INSCRIPTIONS: dict[str, list[float]] = {}
_INSCR_LOCK = threading.Lock()
INSCR_MAX_PAR_HEURE = 5        # tentatives par adresse IP
ATTENTE_MAX = 20               # comptes en attente de validation au maximum


def _limite_inscription(ip: str):
    import time
    now = time.time()
    with _INSCR_LOCK:
        essais = [t for t in _INSCRIPTIONS.get(ip, []) if now - t < 3600]
        if len(essais) >= INSCR_MAX_PAR_HEURE:
            _INSCRIPTIONS[ip] = essais
            raise HTTPException(429, "Trop de tentatives. Réessayez plus tard.")
        essais.append(now)
        _INSCRIPTIONS[ip] = essais


@public.post("/auth/inscription")
def inscription(b: CompteIn, request: Request, db: Session = Depends(get_db)):
    """Crée un compte responsable INACTIF : un responsable doit l'activer (Admin > Comptes)."""
    _limite_inscription(request.client.host if request.client else "?")
    email = _email(b.email)
    _mdp(b.mot_de_passe)
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "Un compte existe déjà avec cet e-mail.")
    en_attente = db.scalars(select(User).where(User.statut == "en_attente")).all()
    if len(en_attente) >= ATTENTE_MAX:
        raise HTTPException(503, "Trop de demandes en attente. Contactez un responsable.")
    db.add(User(email=email, password_hash=hash_password(b.mot_de_passe), role="haut_responsable",
                actif=False, statut="en_attente"))
    db.commit()
    log_action(db, f"Demande d'inscription : {email}", "système")
    return {"ok": True}

# ---------------- Comptes responsables : tous les comptes ont exactement les mêmes droits ----------------
def _photo(u: User) -> Optional[str]:
    """Adresse de la photo de profil (avec version pour le cache), ou None."""
    v = media.version(f"user_{u.id}")
    return f"/avatars/{u.id}?v={v}" if v else None


def _principal_id(db: Session) -> Optional[int]:
    """Le compte principal est le premier compte créé."""
    return db.scalars(select(User.id).order_by(User.id).limit(1)).first()


def _compte_out(u: User, courant: str, principal_id: Optional[int] = None) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role, "actif": u.actif, "date_creation": u.date_creation,
            "moi": u.email == courant, "photo": _photo(u), "principal": u.id == principal_id}


class CompteIn(BaseModel):
    email: str = Field(max_length=254)
    mot_de_passe: str = Field(max_length=200)


class MotDePasseIn(BaseModel):
    ancien: str = Field(max_length=200)
    nouveau: str = Field(max_length=200)


class ActifIn(BaseModel):
    actif: bool


@public.get("/sante")
def sante():
    return {"ok": True}


@public.get("/avatars/{uid}")
def avatar(uid: int):
    """Photo de profil d'un compte (affichée par <img>, qui ne peut pas envoyer de jeton)."""
    p = media.chemin(f"user_{uid}")
    if not p.exists():
        raise HTTPException(404, "Pas de photo")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


# ---------------- Projets (sélection du projet actif) et référentiels ----------------
@router.get("/projets")
def liste_projets(db: Session = Depends(get_db)):
    """Projets (page de transition) : chiffres de situation, avancement moyen, prochaine échéance, équipe mobilisée."""
    plist = projects.sync(db)
    try:
        tickets = crm.list_tickets()
        roster = {m["id"]: m for m in crm.membres()}
    except Exception as e:
        raise _crm_down(e)
    p = settings_store.params(db)
    now = dt.datetime.now()
    today = now.date().isoformat()
    out = []
    for pr in plist:
        ts = [t for t in tickets if t["projet_id"] == pr.crm_projet_id]
        trs = [T.compute_tracking(t, now, p["holidays"], p["seuil_jours"], p["seuil_avancement"], p["work_end"]) for t in ts]
        ouverts = [t for t in ts if t["statut"] != "ferme"]
        prochaines = sorted(str(t["echeance"]) for t in ouverts if str(t["echeance"]) >= today)
        ids_equipe = list(dict.fromkeys(i for t in ts for i in t["membre_ids"]))
        out.append({"id": pr.id, "nom": pr.nom, "statut": pr.statut, "date_limite": pr.date_limite, "nb_tickets": len(ts),
                    "nb_en_retard": sum(x["situation"] == "en_retard" for x in trs),
                    "nb_a_surveiller": sum(x["situation"] == "a_surveiller" for x in trs),
                    "nb_fermes": sum(x["situation"] == "ferme" for x in trs),
                    "avancement": round(sum(t["avancement_declare"] for t in ts) / len(ts)) if ts else 0,
                    "prochaine_echeance": prochaines[0] if prochaines else None,
                    "equipe": [{"id": i, "nom": roster[i]["nom"], "photo": roster[i].get("photo")} for i in ids_equipe if i in roster]})
    return out


@router.get("/projets/nom-disponible")
def nom_disponible(nom: str = "", db: Session = Depends(get_db)):
    """Contrôle en direct du formulaire de dépôt : le nom saisi est-il déjà celui d'un projet ?"""
    propre = projects.nom_propre(nom)
    deja = projects.nom_existant(db, propre) if propre else None
    return {"disponible": deja is None, "existant": deja,
            "message": f"Un projet nommé « {deja} » existe déjà. Choisissez un autre nom de projet." if deja else ""}


@router.get("/crm/membres")
def crm_membres():
    try:
        return crm.membres()
    except Exception as e:
        raise _crm_down(e)


# ---------------- Création des tâches ----------------
def tache_out(t: Tache) -> dict:
    return {c: getattr(t, c) for c in (
        "id", "ordre", "titre", "description", "priorite", "raison_priorite", "duree_estimee",
        "duree_proposee", "depend_de", "source_dans_document", "niveau_confiance", "profil_recommande", "ambiguites",
        "membre_ids", "statut_relecture", "origine", "id_ticket_crm")} | {
        "echeance": t.date_echeance_initiale, "criteres_acceptation": list(t.criteres_acceptation or []),
        # priorité toujours dans le vocabulaire actuel (priorité / secondaire / bonus), même pour d'anciennes lignes
        "priorite": T.normaliser_priorite(t.priorite) or "secondaire"}


def cahier_out(c: CahierDesCharges) -> dict:
    return {"id": c.id, "statut": c.statut, "nom_projet": c.nom_projet, "nom_fichier": c.nom_fichier,
            "date_depot": c.date_depot, "projet_id": c.projet_id, "ambiguites": c.ambiguites,
            "taches": [tache_out(t) for t in c.taches if t.statut_relecture != "supprimee"]}


@router.get("/cahiers")
def liste_cahiers(db: Session = Depends(get_db)):
    cs = db.scalars(select(CahierDesCharges).order_by(CahierDesCharges.id.desc()).limit(30)).all()
    return [{"id": c.id, "nom_projet": c.nom_projet, "nom_fichier": c.nom_fichier, "statut": c.statut,
             "date_depot": c.date_depot, "projet_id": c.projet_id,
             "nb_taches": len([t for t in c.taches if t.statut_relecture != "supprimee"])} for c in cs]


@router.post("/cahiers")
def deposer_cahier(nom_projet: str = Form(...), texte: str = Form(""), fichier: Optional[UploadFile] = File(None),
                   db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Import (PDF, Word, image, texte) → extraction/OCR → agent → brouillon à relire. Le projet n'est créé qu'à la validation."""
    nom_projet = projects.nom_propre(nom_projet)
    if len(nom_projet) < 2:
        raise HTTPException(400, "Indiquez le nom du projet")
    projects.verifier_nom_unique(db, nom_projet)          # jamais deux projets de même nom (refusé avant tout travail de l'agent)
    nom = "texte saisi"
    if fichier and fichier.filename:
        suffix = Path(fichier.filename).suffix.lower()
        if suffix not in T.EXT_OK:
            raise HTTPException(400, "Format non pris en charge (PDF, Word, PowerPoint, Excel, image, texte…)")
        data = fichier.file.read(settings_max_bytes() + 1)      # jamais plus que la limite en mémoire
        if len(data) > settings_max_bytes():
            raise HTTPException(413, "Fichier trop volumineux")
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            with tmp:
                tmp.write(data)
            texte, nom = T.extract_text(tmp.name), fichier.filename
        except T.ExtractionError as e:
            raise HTTPException(400, str(e))          # message clair pour l'utilisateur
        except Exception:
            log.exception("Extraction impossible pour %s", fichier.filename)   # détail dans la console du serveur
            raise HTTPException(400, "Fichier illisible ou protégé")
        finally:
            os.unlink(tmp.name)
    else:
        texte = T.clean_text(texte)
    if len(texte) < 30:
        raise HTTPException(400, "Aucun texte exploitable trouvé. Si c'est un scan ou une photo, "
                                 "vérifiez qu'il est net, bien orienté et assez grand.")
    try:
        # Un nouveau projet repart de zéro : les tickets des autres projets ne sont jamais fournis à l'agent
        ctx = {"tickets": [], "membres": crm.membres(), "profils": crm.profils()}
    except Exception as e:
        raise _crm_down(e)
    try:
        res = agent.create_tasks(texte, ctx)
    except llm.LLMError as e:
        raise HTTPException(502, f"Modèle d'IA indisponible : {e}")
    except Exception:
        log.exception("Analyse du cahier des charges impossible")
        raise HTTPException(502, "L'analyse du cahier des charges a échoué (réponse du modèle inexploitable). Réessayez ou changez de modèle.")
    if not res:
        raise HTTPException(502, "L'agent n'a pas produit de tâches exploitables. Réessayez ou changez de modèle.")
    affectation.affecter(res["taches"], ctx["membres"], ctx["tickets"])      # après le contrôle, jamais avant
    c = CahierDesCharges(nom_projet=nom_projet, nom_fichier=nom, texte=texte, ambiguites=res["ambiguites_globales"])
    for t in res["taches"]:
        d = max(1, int(t["duree_estimee_jours"]))
        c.taches.append(Tache(
            ordre=t["id"], titre=t["titre"], description=t.get("description", ""),
            criteres_acceptation=T.clean_criteria(t.get("criteres_acceptation")),
            priorite=T.normaliser_priorite(t.get("priorite")) or "secondaire",      # l'ancien vocabulaire (haute/moyenne/basse) est converti
            raison_priorite=t.get("raison_priorite", ""), duree_estimee=d, duree_proposee=d,
            depend_de=t.get("depend_de") or [], source_dans_document=t.get("source_dans_document", ""),
            niveau_confiance=t["niveau_confiance"], profil_recommande=t.get("profil_recommande", ""),
            ambiguites=t["ambiguites"], membre_ids=t["membre_ids_proposes"]))
    db.add(c)
    db.commit()
    log_action(db, f"Dépôt du cahier des charges « {nom} » (projet « {nom_projet} ») : {len(c.taches)} tâches proposées", user)
    return cahier_out(c)


def settings_max_bytes() -> int:
    from .config import settings
    return settings.upload_max_mb * 1024 * 1024


class TacheIn(BaseModel):
    titre: Optional[str] = Field(None, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    criteres_acceptation: Optional[list[str]] = Field(None, max_length=12)
    priorite: Optional[str] = Field(None, pattern="^(priorité|secondaire|bonus)$")
    duree_estimee: Optional[int] = Field(None, ge=1, le=250)
    membre_ids: Optional[list[int]] = None
    depend_de: Optional[list[int]] = None


def _brouillon(db: Session, cid: int) -> CahierDesCharges:
    c = db.get(CahierDesCharges, cid)
    if not c:
        raise HTTPException(404, "Cahier des charges introuvable")
    return c


@router.get("/cahiers/{cid}")
def lire_cahier(cid: int, db: Session = Depends(get_db)):
    return cahier_out(_brouillon(db, cid))


@router.delete("/cahiers/{cid}")
def abandonner_cahier(cid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Brouillon abandonné, ou entrée supprimée de l'historique des cahiers. Le projet et les tickets déjà créés dans le CRM
    ne sont jamais touchés : seule la trace du cahier (et ses tâches de relecture) disparaît."""
    c = _brouillon(db, cid)
    if c.statut == "brouillon":
        log_action(db, f"Brouillon « {c.nom_projet} » abandonné", user)
    else:
        log_action(db, f"Cahier des charges « {c.nom_projet} » supprimé de l'historique", user)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.put("/taches/{tid}")
def modifier_tache(tid: int, b: TacheIn, db: Session = Depends(get_db)):
    t = db.get(Tache, tid)
    if not t or t.id_ticket_crm:
        raise HTTPException(409, "Tâche introuvable ou déjà transmise au CRM")
    changes = b.model_dump(exclude_none=True)
    if "criteres_acceptation" in changes:          # saisie humaine : nettoyée (puces, doublons, longueur), jamais jugée sur le fond
        changes["criteres_acceptation"] = T.clean_criteria(changes["criteres_acceptation"])
    if "depend_de" in changes:
        autres = {x.ordre for x in t.cahier.taches if x.statut_relecture != "supprimee" and x.id != t.id}
        changes["depend_de"] = [d for d in changes["depend_de"] if d in autres]
    for k, v in changes.items():
        setattr(t, k, v)
    t.modifiee_par_admin = True
    if t.origine == "agent":
        t.statut_relecture = "modifiee"
    db.commit()
    return tache_out(t)


@router.delete("/taches/{tid}")
def supprimer_tache(tid: int, db: Session = Depends(get_db)):
    t = db.get(Tache, tid)
    if not t or t.id_ticket_crm:
        raise HTTPException(409, "Tâche introuvable ou déjà transmise au CRM")
    t.statut_relecture = "supprimee"
    for o in t.cahier.taches:                      # les dépendances vers une tâche supprimée disparaissent
        if t.ordre in (o.depend_de or []):
            o.depend_de = [d for d in o.depend_de if d != t.ordre]
    db.commit()
    return {"ok": True}


class NouvelleTache(BaseModel):
    titre: str = Field(min_length=2, max_length=300)
    description: str = Field("", max_length=5000)
    criteres_acceptation: list[str] = Field(default_factory=list, max_length=12)
    priorite: str = Field("secondaire", pattern="^(priorité|secondaire|bonus)$")
    duree_estimee: int = Field(1, ge=1, le=250)
    membre_ids: list[int] = []


@router.post("/cahiers/{cid}/taches")
def ajouter_tache(cid: int, b: NouvelleTache, db: Session = Depends(get_db)):
    c = _brouillon(db, cid)
    champs = b.model_dump() | {"criteres_acceptation": T.clean_criteria(b.criteres_acceptation)}
    t = Tache(cahier_id=cid, ordre=max([x.ordre for x in c.taches] + [0]) + 1, origine="manuel",
              statut_relecture="acceptee", modifiee_par_admin=True, duree_proposee=b.duree_estimee, **champs)
    db.add(t)
    db.commit()
    return tache_out(t)


_validations_en_cours: set[int] = set()
_validations_verrou = threading.Lock()


@router.post("/cahiers/{cid}/valider")
def valider(cid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Validation humaine → création du projet → échéances (en jours) → tickets via le connecteur → e-mails.
    Une seule validation à la fois par cahier : un double clic ne peut ni dupliquer les tickets ni renvoyer les e-mails."""
    with _validations_verrou:
        if cid in _validations_en_cours:
            raise HTTPException(409, "Validation déjà en cours pour ce cahier des charges.")
        _validations_en_cours.add(cid)
    try:
        return _valider(cid, db, user)
    finally:
        with _validations_verrou:
            _validations_en_cours.discard(cid)


def _valider(cid: int, db: Session, user: str):
    c = _brouillon(db, cid)
    if c.statut == "valide":
        raise HTTPException(409, "Cahier déjà validé")
    actives = [t for t in c.taches if t.statut_relecture != "supprimee"]
    if not actives:
        raise HTTPException(400, "Aucune tâche à valider")
    dep = T.check_dependencies([{"id": t.ordre, "depend_de": t.depend_de} for t in actives])
    if not dep["ok"]:
        raise HTTPException(400, f"Dépendances invalides (cycle ou référence inconnue) : {dep}")
    try:
        membres = {m["id"]: m for m in crm.membres()}
        # Aucun ticket sans responsable : une tâche non affectée bloque la validation (rien n'est créé tant que ce n'est pas corrigé)
        sans = [t.titre for t in actives if not t.id_ticket_crm and not [i for i in (t.membre_ids or []) if i in membres]]
        if sans:
            liste = " ; ".join(f"« {x} »" for x in sans[:5]) + (f" et {len(sans) - 5} autre(s)" if len(sans) > 5 else "")
            raise HTTPException(400, f"{len(sans)} tâche(s) sans membre affecté : {liste}. Affectez au moins un membre à chaque tâche avant de valider.")
        if not c.projet_id:                        # un cahier validé = un projet (créé ici, jamais avant la validation)
            c.nom_projet = projects.verifier_nom_unique(db, c.nom_projet)   # un autre projet a pu prendre ce nom depuis le dépôt
            cp = crm.create_projet(c.nom_projet)
            c.projet = projects.get_or_create_for_crm(db, cp["id"], c.nom_projet)
            db.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise _crm_down(e)
    projet = c.projet
    hol = settings_store.params(db)["holidays"]
    par_ordre = {t.ordre: t for t in actives}
    today, erreurs, crees, mails_ok, mails_ko = dt.date.today(), [], 0, 0, 0
    a_notifier: list = []
    sans_membre, causes_mail, destinataires_ok = 0, [], []
    for ordre in dep["ordre"]:                      # les tâches préalables sont créées en premier
        t = par_ordre[ordre]
        if t.id_ticket_crm:                         # déjà créée lors d'une validation partielle précédente
            continue
        echeance = add_bd(today, t.duree_estimee, hol)
        crit, _defaut = T.assurer_criteres(t.criteres_acceptation, t.titre, t.description or "", t.source_dans_document or "")
        if _defaut:                                 # une tâche n'est jamais créée sans critère d'acceptation
            t.criteres_acceptation = crit
        try:
            res = crm.create_ticket({
                "titre": t.titre, "projet_id": projet.crm_projet_id, "echeance": str(echeance),
                "description": str(t.description or ""),
                "criteres_acceptation": list(crit),
                "membre_ids": [i for i in t.membre_ids if i in membres], "date_creation": str(today),
                "depend_de_ids": [par_ordre[d].id_ticket_crm for d in t.depend_de
                                  if d in par_ordre and par_ordre[d].id_ticket_crm]})
        except Exception as e:
            erreurs.append(f"« {t.titre} » : {e}")
            continue
        t.id_ticket_crm = res["id"]
        t.date_echeance_initiale = echeance         # figée ensuite par le trigger PostgreSQL
        if t.statut_relecture == "proposee":
            t.statut_relecture = "acceptee"
        db.commit()
        crees += 1
        if not [i for i in t.membre_ids if i in membres]:
            sans_membre += 1                        # aucun destinataire : aucun e-mail possible pour cette tâche
        for mid in t.membre_ids:                    # notification d'affectation : envoyée en un seul lot après la création
            m = membres.get(mid)
            if m:
                a_notifier.append((t.id, res["id"], m, mailer.affectation_text(m["nom"], t.titre, res["id"], echeance, projet.nom), t.titre))
        db.commit()
    # Envoi des e-mails : UNE connexion SMTP pour tout le lot (un serveur injoignable n'est testé qu'une fois). Un échec
    # d'envoi n'annule jamais la création des tickets ; chaque e-mail est consigné au journal avec son résultat réel.
    if a_notifier:
        issues = mailer.send_batch([(m["email"], texte, f"Nouveau ticket : {titre}") for _, _, m, texte, titre in a_notifier])
        for (id_tache, id_ticket, m, texte, _titre), (statut_envoi, detail) in zip(a_notifier, issues):
            if statut_envoi == "envoye":
                mails_ok += 1
                if m['email'] not in destinataires_ok:
                    destinataires_ok.append(m['email'])
                log_action(db, f"E-mail d'affectation envoyé à {m['email']} (T-{id_ticket:03d})", "système")
            else:
                mails_ko += 1
                if detail and detail not in causes_mail:
                    causes_mail.append(detail)
                log_action(db, f"E-mail d'affectation non envoyé à {m['email']} : {detail}", "système")
            db.add(Notification(id_tache=id_tache, destinataire=m["email"], texte=texte,
                                statut="envoye" if statut_envoi == "envoye" else "echec"))
        db.commit()
    echs = [t.date_echeance_initiale for t in actives if t.date_echeance_initiale]
    if echs:
        projet.date_limite = max(echs)
    c.statut = "valide" if not erreurs else "partiel"
    db.commit()
    log_action(db, f"Validation du cahier {cid} : projet « {projet.nom} » créé, {crees} ticket(s) créé(s) dans le CRM", user)
    return {"tickets_crees": crees, "erreurs": erreurs, "statut": c.statut, "projet_id": projet.id, "projet": projet.nom,
            "mails_envoyes": mails_ok, "mails_en_echec": mails_ko, "mails_causes": causes_mail[:3],
            "destinataires": destinataires_ok, "taches_sans_membre": sans_membre,
            "envoi_reel": str(mailer.config_effective(None)["server"]).strip().lower() not in ("localhost", "127.0.0.1", "::1", "")}


# ---------------- Suivi : tableau de bord, analyse, synthèse (toujours pour UN projet) ----------------
def _stats(tickets: dict, tracking: dict) -> dict:
    par_statut = {s: sum(t["statut"] == s for t in tickets.values()) for s in ("nouveau", "ouvert", "en_cours", "en_attente", "ferme")}
    return {"total": len(tickets), "par_statut": par_statut,
            "en_retard": sum(tr["situation"] == "en_retard" for tr in tracking.values()),
            "a_surveiller": sum(tr["situation"] == "a_surveiller" for tr in tracking.values()),
            "a_cloturer": sum(bool(tr.get("cloture_a_valider")) for tr in tracking.values()),   # 100 % déclaré, clôture en attente de décision
            # « en attente » hors tâches déjà comptées en retard / à surveiller : chaque tâche n'est comptée qu'une fois
            "en_attente_seule": sum(t["statut"] == "en_attente" and tracking[i]["situation"] not in ("en_retard", "a_surveiller")
                                    for i, t in tickets.items())}


def _a_jour(db: Session, projet: Projet, tickets: dict, tracking: dict) -> None:
    """La synthèse, les prévisions de risque et les recommandations stockées doivent refléter l'état réel du CRM. Si une
    échéance (ou un statut) a changé depuis la dernière analyse, la phase rapide est relancée immédiatement (calcul Python)."""
    derniere = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == projet.id)
                          .order_by(SyntheseSuivi.id.desc()).limit(1)).first()
    if derniere is None or not service.ecarts(derniere.chiffres, tickets, tracking)[1]:
        return
    try:
        if service.synchroniser(projet.id):
            db.expire_all()
    except Exception as e:                       # la lecture ne doit jamais échouer à cause de la resynchronisation
        log.warning("Resynchronisation du projet « %s » impossible : %s", projet.nom, e)


@router.get("/projets/{pid}/dashboard")
def dashboard(pid: int, db: Session = Depends(get_db)):
    projet = projects.get(db, pid)
    try:
        tickets, tracking, _ = service.snapshot(db, projet)
        roster = crm.membres()
        membres = {m["id"]: m["nom"] for m in roster}
    except Exception as e:
        raise _crm_down(e)
    rows = [{"id": i, "titre": t["titre"], "statut": t["statut"], "avancement_declare": t["avancement_declare"],
             "situation": tracking[i]["situation"], "etat_echeance": tracking[i]["libelle"], "echeance": t["echeance"],
             "cloture_a_valider": bool(tracking[i].get("cloture_a_valider")),
             "membre_ids": t["membre_ids"], "membres": [membres.get(m, "?") for m in t["membre_ids"]]}
            for i, t in tickets.items()]
    return {"projet": {"id": projet.id, "nom": projet.nom, "date_limite": projet.date_limite},
            "stats": _stats(tickets, tracking), "tickets": rows,
            "membres": [{"id": m["id"], "nom": m["nom"], "profil": m["profil"], "photo": m.get("photo")} for m in roster]}


def _etat_criteres(db: Session, tid: int, t: dict, tache) -> dict:
    """Critères d'un ticket (toujours au moins un) et état des cases cochées ; la clôture exige 100 % ET tous les critères cochés."""
    cochés = {v.critere for v in db.scalars(select(ValidationCritere).where(ValidationCritere.id_ticket == tid))}
    return T.etat_criteres(t.get("criteres_acceptation"), tache.criteres_acceptation if tache else None, t["titre"],
                           t.get("description") or "", tache.source_dans_document if tache else "", cochés,
                           t["statut"], t.get("avancement_declare"))


@router.get("/tickets/{tid}/analyse")
def analyse(tid: int, db: Session = Depends(get_db)):
    try:
        t = crm.get_ticket(tid)
    except Exception:
        raise HTTPException(404, "Ticket introuvable")
    projet = projects.of_ticket(db, t)
    tickets, tracking, _ = service.snapshot(db, projet)
    _a_jour(db, projet, tickets, tracking)
    titre = lambda i: {"id": i, "titre": tickets[i]["titre"], "statut": tickets[i]["statut"]}
    a = db.scalars(select(AnalyseTicket).where(AnalyseTicket.id_ticket == tid).order_by(AnalyseTicket.id.desc())).first()
    recos = db.scalars(select(Recommandation).where(Recommandation.id_ticket == tid, Recommandation.obsolete.is_(False))
                       .order_by(Recommandation.id.desc()).limit(5)).all()
    tache = db.scalars(select(Tache).where(Tache.id_ticket_crm == tid)).first()
    etat = _etat_criteres(db, tid, t, tache)
    return {"projet": {"id": projet.id, "nom": projet.nom}, "ticket": t, "calculs": tracking[tid], **etat,
            "critere_source": tache.source_dans_document if tache else "",
            "historique": crm.historique(tid), "membres": crm.membres_du_ticket(tid),
            "bloque": [titre(i) for i, o in tickets.items() if tid in o["depend_de_ids"]],
            "depend_de": [titre(i) for i in t["depend_de_ids"] if i in tickets],
            "analyse": a.contenu if a else None, "analyse_date": a.date if a else None,
            "recommandations": [{"id": r.id, "texte": r.texte, "date": r.date, "decision": r.decision} for r in recos]}


@router.get("/tickets/{tid}/criteres")
def criteres_du_ticket(tid: int, db: Session = Depends(get_db)):
    """Critères d'acceptation d'un ticket (écrits à la création du ticket, après validation du responsable)."""
    try:
        t = crm.get_ticket(tid)
    except httpx.HTTPStatusError as e:
        raise HTTPException(404, "Ticket introuvable") if e.response.status_code == 404 else _crm_down(e)
    except Exception as e:
        raise _crm_down(e)
    tache = db.scalars(select(Tache).where(Tache.id_ticket_crm == tid)).first()
    return {"ticket_id": tid, "titre": t["titre"], **_etat_criteres(db, tid, t, tache),
            "source_dans_document": tache.source_dans_document if tache else ""}


class ValidationCritereIn(BaseModel):
    valide: bool


@router.put("/tickets/{tid}/criteres/{indice}/validation")
def valider_critere(tid: int, indice: int, b: ValidationCritereIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Coche / décoche un critère d'acceptation (haut responsable). `indice` = position (à partir de 0) dans la liste des critères."""
    try:
        t = crm.get_ticket(tid)
    except httpx.HTTPStatusError as e:
        raise HTTPException(404, "Ticket introuvable") if e.response.status_code == 404 else _crm_down(e)
    except Exception as e:
        raise _crm_down(e)
    if t["statut"] == "ferme":
        raise HTTPException(409, "Ticket fermé : les critères ne sont plus modifiables")
    tache = db.scalars(select(Tache).where(Tache.id_ticket_crm == tid)).first()
    criteres = _etat_criteres(db, tid, t, tache)["criteres_acceptation"]
    if not 0 <= indice < len(criteres):
        raise HTTPException(404, "Critère introuvable")
    texte = criteres[indice]
    existant = db.scalars(select(ValidationCritere).where(ValidationCritere.id_ticket == tid, ValidationCritere.critere == texte)).all()
    if b.valide and not existant:
        db.add(ValidationCritere(id_ticket=tid, critere=texte, valide_par=user))
        log_action(db, f"Critère {indice + 1} de T-{tid:03d} validé", user)
    elif not b.valide and existant:
        for v in existant:
            db.delete(v)
        log_action(db, f"Critère {indice + 1} de T-{tid:03d} décoché", user)
    db.commit()
    return {"ticket_id": tid, **_etat_criteres(db, tid, t, tache)}


@router.get("/projets/{pid}/cahier")
def cahier_du_projet(pid: int, db: Session = Depends(get_db)):
    """Cahier des charges validé du projet (tâches, durées, affectations et dépendances), pour la consultation dans le suivi."""
    projects.get(db, pid)
    c = db.scalars(select(CahierDesCharges).where(CahierDesCharges.projet_id == pid)).first()
    try:
        roster = {m["id"]: {"id": m["id"], "nom": m["nom"], "profil": m["profil"], "photo": m.get("photo")} for m in crm.membres()}
    except Exception as e:
        raise _crm_down(e)
    if not c:                                         # projet créé directement dans le CRM : pas de cahier à afficher
        return {"cahier": None, "membres": list(roster.values())}
    return {"cahier": cahier_out(c) | {"statut_projet": c.projet.statut if c.projet else None}, "membres": list(roster.values())}


@router.get("/projets/{pid}/historique")
def historique_projet(pid: int, du: Optional[dt.date] = None, au: Optional[dt.date] = None, db: Session = Depends(get_db)):
    """Journal de bord d'UN projet, filtrable par période. Reconstitué sans nouvelle table à partir des traces existantes :
    entrées du journal qui citent le projet ou l'un de ses tickets, évolutions constatées par l'agent, décisions sur les
    recommandations et rapports générés. Rien d'un autre projet n'y figure."""
    projet = projects.get(db, pid)
    if du and au and du > au:
        raise HTTPException(422, "La date de début doit précéder la date de fin.")
    try:
        ids = {t["id"] for t in crm.list_tickets(projet_id=projet.crm_projet_id)}
    except Exception as e:
        raise _crm_down(e)
    ids_re = re.compile(r"T-0*(\d+)")
    bornes = []
    if du:
        bornes.append(lambda d: d >= dt.datetime.combine(du, dt.time.min))
    if au:
        bornes.append(lambda d: d < dt.datetime.combine(au + dt.timedelta(days=1), dt.time.min))
    dans = lambda d: all(b(d) for b in bornes)
    entrees: list[dict] = []

    # 1) Journal des actions : celles qui citent « ce projet » ou un de ses tickets (identifiants uniques dans tout le CRM)
    for j in db.scalars(select(JournalAction).order_by(JournalAction.id.desc()).limit(3000)):
        cite_ticket = any(int(x) in ids for x in ids_re.findall(j.action))
        cite_projet = f"« {projet.nom} »" in j.action
        if (cite_ticket or cite_projet) and dans(j.date):
            entrees.append({"date": j.date, "type": "action", "texte": j.action, "auteur": j.auteur})
    # 2) Évolutions constatées par l'agent (dernière synthèse : 24 h glissantes, avec heure précise)
    s = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == pid).order_by(SyntheseSuivi.id.desc())).first()
    for e in ((s.chiffres or {}).get("evolutions_hist") or []) if s else []:
        try:
            d = dt.datetime.fromisoformat(e["t"])
        except (KeyError, ValueError, TypeError):
            continue
        if dans(d):
            entrees.append({"date": d, "type": "evolution", "texte": e["txt"], "auteur": "agent"})
    # 3) Recommandations émises (et leur décision)
    for r in db.scalars(select(Recommandation).where(Recommandation.id_projet == pid).order_by(Recommandation.id.desc()).limit(300)):
        if dans(r.date) and not r.obsolete:
            etat = {"suivie": "suivie", "rejetee": "rejetée"}.get(r.decision or "", "en attente de décision")
            entrees.append({"date": r.date, "type": "recommandation", "texte": f"Recommandation émise ({etat}) : {r.texte}", "auteur": "agent"})
    # 4) Rapports générés
    for r in db.scalars(select(Rapport).where(Rapport.id_projet == pid).order_by(Rapport.id.desc()).limit(100)):
        if dans(r.date):
            entrees.append({"date": r.date, "type": "rapport", "texte": f"Rapport {r.format.upper()} généré", "auteur": "responsable"})
    # Doublons éventuels (même texte à la même seconde) retirés, du plus récent au plus ancien
    vus, out = set(), []
    for e in sorted(entrees, key=lambda x: x["date"], reverse=True):
        cle = (e["date"].replace(microsecond=0), e["texte"])
        if cle not in vus:
            vus.add(cle)
            out.append(e)
    return {"projet": {"id": projet.id, "nom": projet.nom}, "entrees": out[:500]}


@router.get("/projets/{pid}/synthese")
def synthese(pid: int, db: Session = Depends(get_db)):
    projet = projects.get(db, pid)
    try:
        tickets, tracking, _ = service.snapshot(db, projet)
    except Exception as e:
        raise _crm_down(e)
    _a_jour(db, projet, tickets, tracking)
    s = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == pid).order_by(SyntheseSuivi.id.desc())).first()
    recos = db.scalars(select(Recommandation).where(Recommandation.id_projet == pid, Recommandation.decision.is_(None),
                                                    Recommandation.obsolete.is_(False))
                       .order_by(Recommandation.id.desc()).limit(30)).all()
    ouvertes = [{"id": r.id, "id_ticket": r.id_ticket, "titre": tickets.get(r.id_ticket, {}).get("titre", ""),
                 "texte": r.texte, "date": r.date, "diagnostic": r.diagnostic} for r in recos]
    bloquants = {d for o in tickets.values() if o["statut"] != "ferme" for d in o["depend_de_ids"]}
    sans_motif = [i for i, tr in tracking.items() if tr["situation"] == "en_retard" and tickets[i]["statut"] != "en_attente"
                  and not (tickets[i].get("motif_retard_courant") or tickets[i].get("motif_attente_courant"))]
    detection = {"en_retard": sum(tr["situation"] == "en_retard" for tr in tracking.values()),
                 "a_surveiller": sum(tr["situation"] == "a_surveiller" for tr in tracking.values()),
                 "retards_sans_motif": len(sans_motif),
                 "en_attente": _stats(tickets, tracking)["en_attente_seule"],
                 "retards_bloquants": sum(1 for i, tr in tracking.items() if tr["situation"] == "en_retard" and i in bloquants)}
    base = {"projet": {"id": projet.id, "nom": projet.nom, "date_limite": projet.date_limite},
            "stats": _stats(tickets, tracking), "detection": detection, "recommandations": ouvertes,
            "taches": [{"id": i, "titre": t["titre"], "statut": t["statut"], "avancement": t["avancement_declare"],
                        "situation": tracking[i]["situation"], "etat": tracking[i]["libelle"], "echeance": t["echeance"]}
                       for i, t in tickets.items()],
            "en_clair": plain.en_clair(tickets, tracking, settings_store.params(db)["holidays"]),
            "suivi": service.couverture(db, projet.id, tickets, tracking)}
    if not s:
        return {**base, "synthese": None}
    ch = s.chiffres
    prio = [{**p, "titre": tickets[p["id"]]["titre"]} for p in ch.get("priorites", []) if p["id"] in tickets]
    risques = [{**r, "titre": tickets[r["id"]]["titre"]} for r in ch.get("risques", []) if r["id"] in tickets]
    return {**base, "synthese": {"id": s.id, "date": s.date, "declencheur": s.declencheur, "contenu": s.contenu,
                                 "source": ch.get("source", ""), "evolutions": ch.get("evolutions_hist") or [{"t": s.date.isoformat(), "txt": e} for e in ch.get("evolutions", [])],
                                 "priorites": prio, "risques": risques}}


class Decision(BaseModel):
    decision: str = Field(pattern="^(suivie|rejetee)$")


@router.post("/recommandations/{rid}/decision")
def decider(rid: int, b: Decision, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Suivre ou rejeter uniquement : une recommandation ne se modifie pas, et sa décision est définitive."""
    r = db.get(Recommandation, rid)
    if not r:
        raise HTTPException(404)
    if r.decision:
        raise HTTPException(409, "Décision déjà enregistrée")
    r.decision = b.decision
    db.commit()
    log_action(db, f"Recommandation {rid} (T-{r.id_ticket:03d}) : {b.decision}", user)
    return {"ok": True}


class EcheanceIn(BaseModel):
    nouvelle_date: dt.date
    motif: str = Field(min_length=3, max_length=500)


@router.put("/tickets/{tid}/echeance")
def modifier_echeance(tid: int, b: EcheanceIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Décision humaine : seul chemin d'écriture de l'échéance, tracé au journal (ancienne, nouvelle, motif, date, auteur)."""
    try:
        t = crm.get_ticket(tid)
    except Exception:
        raise HTTPException(404, "Ticket introuvable")
    if t["statut"] == "ferme":
        raise HTTPException(409, "Ticket fermé : son échéance ne se modifie plus")
    if b.nouvelle_date < dt.date.today():
        raise HTTPException(422, "La nouvelle échéance ne peut pas être antérieure à aujourd'hui")
    if str(t["echeance"]) == str(b.nouvelle_date):
        raise HTTPException(409, "La nouvelle échéance est identique à l'actuelle")
    projet = projects.of_ticket(db, t)
    crm.set_echeance(tid, b.nouvelle_date)
    log_action(db, f"Échéance T-{tid:03d} : {t['echeance']} → {b.nouvelle_date}. Motif : {b.motif}", user)
    # Prise en compte IMMÉDIATE : la phase rapide (analyse, risque, recommandation, synthèse recalculés par Python) est terminée
    # avant la réponse ; seul l'affinage par l'IA se poursuit en arrière-plan. Le prochain affichage montre donc déjà la nouvelle situation.
    try:
        service.reevaluate(projet.id, {tid}, "modification de l'échéance")
    except Exception as e:
        log.error("Réévaluation après modification de l'échéance de T-%s : %s (reprise automatique au prochain affichage)", tid, e)
    return {"ok": True}


@router.post("/tickets/{tid}/cloture")
def cloturer_ticket(tid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Validation de la clôture par le haut responsable connecté : SEUL chemin qui ferme un ticket. Le taux d'avancement
    (même 100 %) et le statut sont indépendants ; ni le CRM, ni le suivi automatique, ni l'agent ne ferment un ticket."""
    try:
        t = crm.get_ticket(tid)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, "Ticket introuvable")
        raise _crm_down(e)
    except Exception as e:
        raise _crm_down(e)
    if t["statut"] == "ferme":
        raise HTTPException(409, "Ticket déjà fermé")
    if int(t.get("avancement_declare") or 0) < 100:      # conditions strictes : 100 % dans le CRM ET tous les critères cochés
        raise HTTPException(409, "Clôture impossible : l'avancement du ticket dans le CRM n'est pas à 100 %.")
    tache = db.scalars(select(Tache).where(Tache.id_ticket_crm == tid)).first()
    if not _etat_criteres(db, tid, t, tache)["tous_criteres_valides"]:
        raise HTTPException(409, "Clôture impossible : tous les critères d'acceptation doivent être cochés.")
    projet = projects.of_ticket(db, t)
    try:
        crm.cloturer(tid, user)
    except httpx.HTTPStatusError as e:
        raise HTTPException(409 if e.response.status_code == 409 else 502, "Clôture refusée par le CRM")
    except Exception as e:
        raise _crm_down(e)
    log_action(db, f"Clôture de T-{tid:03d} validée (statut « {t['statut']} », avancement déclaré {t['avancement_declare']} %)", user)
    try:       # prise en compte immédiate (retard final figé, recommandation ouverte retirée)
        service.reevaluate(projet.id, {tid}, "clôture validée par le responsable")
    except Exception as e:
        log.error("Réévaluation après clôture de T-%s : %s (reprise automatique)", tid, e)
    return {"ok": True}


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation: Optional[str] = Field(default=None, max_length=40)   # identifiant de la discussion (créé par l'interface)


@router.get("/projets/{pid}/chat")
def chat_historique(pid: int, db: Session = Depends(get_db)):
    """Tout l'historique des discussions du projet (rien n'est jamais masqué) ; chaque échange porte l'identifiant de sa discussion.
    Les anciens échanges (sans identifiant) sont regroupés par jour."""
    projects.get(db, pid)
    cs = db.scalars(select(ConversationChat).where(ConversationChat.id_projet == pid)
                    .order_by(ConversationChat.id.desc()).limit(600)).all()[::-1]
    return [{"id": c.id, "date": c.date, "question": c.question, "reponse": c.reponse,
             "conversation": c.id_conversation or f"ancien-{c.date:%Y-%m-%d}",
             "tickets_cites": sorted({int(x) for x in re.findall(r"T-0*(\d+)", c.reponse)})} for c in cs]


@router.post("/projets/{pid}/chat")
def chat(pid: int, b: ChatIn, db: Session = Depends(get_db)):
    projects.get(db, pid)
    cond = [ConversationChat.id_projet == pid]
    if b.conversation:
        cond.append(ConversationChat.id_conversation == b.conversation)   # le contexte du modèle = la discussion en cours
    prev = db.scalars(select(ConversationChat).where(*cond).order_by(ConversationChat.id.desc()).limit(3)).all()[::-1]
    hist = [m for c in prev for m in ({"role": "user", "content": c.question}, {"role": "assistant", "content": c.reponse})]
    try:
        res = service.chat(pid, b.question, hist)
    except llm.LLMError as e:
        res = {"reponse": f"Le modèle d'IA est indisponible : {e}", "tickets_cites": []}
    except Exception as e:
        raise _crm_down(e)
    db.add(ConversationChat(id_projet=pid, question=b.question, reponse=res["reponse"], id_conversation=b.conversation))
    db.commit()
    return res


# ---------------- Rapports (bonus), par projet ----------------
def _rapport(pid: int, fmt: str, db: Session):
    projet = projects.get(db, pid)
    try:
        tickets, tracking, _ = service.snapshot(db, projet)
        noms = {m["id"]: m["nom"] for m in crm.membres()}
    except Exception as e:
        raise _crm_down(e)
    _a_jour(db, projet, tickets, tracking)
    s = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == pid).order_by(SyntheseSuivi.id.desc())).first()
    texte = s.contenu if s else "Aucune synthèse disponible."
    ch = (s.chiffres or {}) if s else {}
    recos = db.scalars(select(Recommandation).where(Recommandation.id_projet == pid, Recommandation.obsolete.is_(False))
                       .order_by(Recommandation.id.desc()).limit(30)).all()
    data = dict(projet=projet.nom, synthese=texte, tickets=tickets, tracking=tracking, stats=_stats(tickets, tracking),
                recos=[(r.texte, r.decision) for r in recos], noms=noms,
                en_clair=plain.en_clair(tickets, tracking, settings_store.params(db)["holidays"]),
                priorites=[{**p, "titre": tickets[p["id"]]["titre"]} for p in ch.get("priorites", []) if p["id"] in tickets],
                risques=[{**r, "titre": tickets[r["id"]]["titre"]} for r in ch.get("risques", []) if r["id"] in tickets],
                evolutions=ch.get("evolutions_hist") or [{"t": s.date.isoformat(), "txt": e} for e in ch.get("evolutions", [])] if s else [])
    try:
        contenu = reports.pdf(**data) if fmt == "pdf" else reports.xlsx(**data)
    except Exception as e:                       # l'échec est expliqué à l'écran au lieu d'un simple « erreur 500 »
        log.exception("Génération du rapport %s impossible (projet %s)", fmt, pid)
        raise HTTPException(500, f"Génération du rapport impossible ({e.__class__.__name__}). Le détail figure dans le journal du serveur.")
    db.add(Rapport(id_projet=pid, format=fmt, contenu=texte))      # tracé seulement si le rapport a bien été produit
    db.commit()
    return contenu


def _entete_fichier(projet_nom: str, pid: int, ext: str) -> dict:
    """En-têtes de téléchargement : nom ASCII sûr + nom UTF-8 lisible (accents, espaces) pour les navigateurs récents."""
    import unicodedata
    from urllib.parse import quote
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", unicodedata.normalize("NFKD", projet_nom).encode("ascii", "ignore").decode()).strip("_") or f"projet_{pid}"
    return {"Content-Disposition": f"attachment; filename=\"rapport_{base}.{ext}\"; filename*=UTF-8''{quote('rapport_' + projet_nom + '.' + ext)}",
            "Cache-Control": "no-store"}


@router.get("/projets/{pid}/rapports/pdf")
def rapport_pdf(pid: int, db: Session = Depends(get_db)):
    contenu = _rapport(pid, "pdf", db)
    return Response(contenu, media_type="application/pdf", headers=_entete_fichier(projects.get(db, pid).nom, pid, "pdf"))


@router.get("/projets/{pid}/rapports/xlsx")
def rapport_xlsx(pid: int, db: Session = Depends(get_db)):
    contenu = _rapport(pid, "xlsx", db)
    return Response(contenu, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_entete_fichier(projects.get(db, pid).nom, pid, "xlsx"))


_RAPPORTS_PRETS: dict[str, tuple[float, bytes, str, dict]] = {}


@router.post("/projets/{pid}/rapports/{fmt}/lien")
def lien_rapport(pid: int, fmt: str, db: Session = Depends(get_db)):
    """Génère le rapport MAINTENANT (toute erreur est donc expliquée à l'écran) puis renvoie un lien de téléchargement
    valable 5 minutes : le navigateur télécharge ensuite le fichier tout prêt, sans transfert par script."""
    import secrets
    import time
    if fmt not in ("pdf", "xlsx"):
        raise HTTPException(404, "Format inconnu")
    nom = projects.get(db, pid).nom
    contenu = _rapport(pid, fmt, db)
    media_type = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    maintenant = time.time()
    for k in [k for k, v in _RAPPORTS_PRETS.items() if v[0] < maintenant]:
        _RAPPORTS_PRETS.pop(k, None)
    jeton = secrets.token_urlsafe(24)
    _RAPPORTS_PRETS[jeton] = (maintenant + 300, contenu, media_type, _entete_fichier(nom, pid, fmt))
    return {"url": f"/api/rapports/fichier/{jeton}", "taille": len(contenu)}


@public.get("/rapports/fichier/{jeton}")
def rapport_pret(jeton: str):
    import time
    x = _RAPPORTS_PRETS.get(jeton)
    if not x or x[0] < time.time():
        raise HTTPException(410, "Lien de téléchargement expiré : relancez la génération du rapport.")
    return Response(x[1], media_type=x[2], headers=x[3])


def _exiger_principal(db: Session, user: str) -> int:
    pid = _principal_id(db)
    courant = db.scalars(select(User).where(User.email == user)).first()
    if not courant or courant.id != pid:
        raise HTTPException(403, "Seul le compte principal peut traiter les comptes.")
    return pid


@router.get("/comptes")
def lister_comptes(db: Session = Depends(get_db), user: str = Depends(current_admin)):
    pid = _principal_id(db)
    rows = db.scalars(select(User).where(User.statut == "accepte").order_by(User.id)).all()
    return [_compte_out(u, user, pid) for u in rows]


@router.put("/comptes/{uid}/actif")
def basculer_actif(uid: int, b: ActifIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    pid = _exiger_principal(db, user)
    u = db.get(User, uid)
    if not u or u.statut != "accepte":
        raise HTTPException(404, "Compte introuvable.")
    if u.id == pid:
        raise HTTPException(400, "Le compte principal ne peut pas être désactivé.")
    u.actif = b.actif
    db.commit()
    log_action(db, f"Compte {'activé' if b.actif else 'désactivé'} : {u.email}", user)
    return _compte_out(u, user, pid)


@router.get("/comptes/demandes")
def lister_demandes(db: Session = Depends(get_db), user: str = Depends(current_admin)):
    _exiger_principal(db, user)
    rows = db.scalars(select(User).where(User.statut == "en_attente").order_by(User.id)).all()
    return [{"id": u.id, "email": u.email, "date_creation": u.date_creation} for u in rows]


@router.post("/comptes/{uid}/accepter")
def accepter_demande(uid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    _exiger_principal(db, user)
    u = db.get(User, uid)
    if not u or u.statut != "en_attente":
        raise HTTPException(404, "Demande introuvable.")
    u.statut, u.actif = "accepte", True
    db.commit()
    log_action(db, f"Inscription acceptée : {u.email}", user)
    return {"ok": True}


@router.post("/comptes/{uid}/refuser")
def refuser_demande(uid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    _exiger_principal(db, user)
    u = db.get(User, uid)
    if not u or u.statut != "en_attente":
        raise HTTPException(404, "Demande introuvable.")
    email = u.email
    db.delete(u)
    db.commit()
    log_action(db, f"Inscription refusée : {email}", user)
    return {"ok": True}


@router.get("/compte/moi")
def mon_compte(db: Session = Depends(get_db), user: str = Depends(current_admin)):
    u = db.scalars(select(User).where(User.email == user)).first()
    if not u:
        raise HTTPException(404, "Compte introuvable")
    return _compte_out(u, user)


@router.post("/compte/photo")
async def changer_photo(fichier: UploadFile = File(...), db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Ajoute ou remplace la photo de profil du compte connecté."""
    u = db.scalars(select(User).where(User.email == user)).first()
    if not u:
        raise HTTPException(404, "Compte introuvable")
    try:
        media.enregistrer(await fichier.read(media.MAX_BYTES + 1), f"user_{u.id}")
    except media.PhotoInvalide as e:
        raise HTTPException(422, str(e))
    log_action(db, "Photo de profil modifiée", user)
    return _compte_out(u, user)


@router.delete("/compte/photo")
def retirer_photo(db: Session = Depends(get_db), user: str = Depends(current_admin)):
    u = db.scalars(select(User).where(User.email == user)).first()
    if not u:
        raise HTTPException(404, "Compte introuvable")
    media.supprimer(f"user_{u.id}")
    log_action(db, "Photo de profil supprimée", user)
    return _compte_out(u, user)


@router.post("/admin/mail/test")
def tester_mail(db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Diagnostic : envoie un e-mail de test au responsable connecté ; le résultat est écrit dans le journal."""
    texte = "Bonjour,\n\nCeci est un e-mail de test envoyé par Agent IA.\n\nCordialement,\nArato – suivi des tâches"
    statut, detail = mailer.send_batch([(user, texte, "Agent IA : e-mail de test")])[0]
    if statut != "envoye":
        log_action(db, f"E-mail d'affectation non envoyé à {user} : {detail}", user)
        raise HTTPException(502, f"Envoi impossible : {detail}")
    log_action(db, f"E-mail d'affectation envoyé à {user} (test)", user)
    return {"ok": True, "destinataire": user}


@router.put("/compte/mot-de-passe")
def changer_mot_de_passe(b: MotDePasseIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    u = db.scalars(select(User).where(User.email == user)).first()
    if not u or not verify_password(b.ancien, u.password_hash):
        raise HTTPException(403, "Mot de passe actuel incorrect.")
    _mdp(b.nouveau)
    if b.nouveau == b.ancien:
        raise HTTPException(422, "Le nouveau mot de passe doit être différent de l'ancien.")
    u.password_hash = hash_password(b.nouveau)
    db.commit()
    log_action(db, "Mot de passe modifié", user)
    return {"ok": True}


@router.put("/comptes/{uid}/actif")
def basculer_actif(uid: int, b: ActifIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    pid = _principal_id(db)
    courant = db.scalars(select(User).where(User.email == user)).first()
    if not courant or courant.id != pid:
        raise HTTPException(403, "Seul le compte principal peut activer ou désactiver des comptes.")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Compte introuvable.")
    if u.id == pid:
        raise HTTPException(400, "Le compte principal ne peut pas être désactivé.")
    u.actif = b.actif
    db.commit()
    log_action(db, f"Compte {'activé' if b.actif else 'désactivé'} : {u.email}", user)
    return _compte_out(u, user, pid)


# ---------------- Administration (bonus) et évaluation ----------------
class AdminSettings(BaseModel):
    seuil_jours: int = Field(ge=0, le=30)
    seuil_avancement: int = Field(ge=0, le=100)
    jours_feries: list[str]
    llm_model: Optional[str] = Field(default=None, min_length=2)   # facultatif : le modèle se change depuis « Modèle d'IA »


@router.get("/admin/settings")
def get_settings(db: Session = Depends(get_db)):
    p = settings_store.params(db)
    return {k: p[k] for k in ("seuil_jours", "seuil_avancement", "jours_feries", "llm_model")}


@router.put("/admin/settings")
def put_settings(b: AdminSettings, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    try:
        [dt.date.fromisoformat(x) for x in b.jours_feries]
    except ValueError:
        raise HTTPException(422, "Jours fériés : format AAAA-MM-JJ")
    for k, v in b.model_dump(exclude_none=True).items():
        settings_store.put(db, k, v)
    log_action(db, f"Paramètres modifiés : seuil {b.seuil_jours} j, avancement {b.seuil_avancement} %, "
               f"{len(b.jours_feries)} jours fériés", user)
    return {"ok": True}


@router.get("/admin/llm")
def llm_info():
    """Fournisseur d'IA en service et modèle actif. La clé d'API n'est JAMAIS exposée (ni sa valeur, ni sa présence)."""
    p = llm.provider()
    return {"hote": p["hote"], "local": p["local"], "modele": llm.current_model()}


class ModeleIn(BaseModel):
    modele: str = Field(min_length=2, max_length=200)


@router.put("/admin/llm/modele")
def llm_changer_modele(b: ModeleIn, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Change le modèle actif ; il est pris en compte dès l'appel suivant de l'agent, sans redémarrage."""
    nouveau = b.modele.strip()
    try:
        disponibles = llm.list_models()
    except llm.LLMError:
        disponibles = []                       # liste indisponible : on laisse le test de connexion trancher
    if disponibles and nouveau not in disponibles:
        raise HTTPException(422, "Ce modèle n'est pas proposé par le fournisseur d'IA.")
    ancien = llm.current_model()
    settings_store.put(db, "llm_model", nouveau)
    settings_store.put(db, "llm_model_fournisseur", llm.fournisseur_cle())   # le choix ne vaut que pour CE fournisseur
    if ancien != nouveau:
        log_action(db, f"Modèle d'IA changé : {ancien} → {nouveau}", user)
    return {"ok": True, "modele": nouveau}


@router.post("/admin/llm/test")
def llm_test():
    """Test réel : serveur joignable, modèle configuré disponible, puis une génération. Chaque étape est expliquée."""
    try:
        return llm.verifier()
    except llm.LLMError as e:
        return {"ok": False, "erreur": str(e)}


@router.get("/admin/llm/modeles")
def llm_modeles():
    try:
        return {"ok": True, "modeles": llm.list_models()}
    except llm.LLMError as e:
        return {"ok": False, "erreur": str(e), "modeles": []}


@router.get("/admin/journal")
def journal(du: Optional[dt.date] = None, au: Optional[dt.date] = None, db: Session = Depends(get_db)):
    """Journal des actions, filtrable par période (du / au inclus, format AAAA-MM-JJ)."""
    if du and au and du > au:
        raise HTTPException(422, "La date de début doit précéder la date de fin.")
    q = select(JournalAction).order_by(JournalAction.id.desc())
    if du:
        q = q.where(JournalAction.date >= dt.datetime.combine(du, dt.time.min))
    if au:
        q = q.where(JournalAction.date < dt.datetime.combine(au + dt.timedelta(days=1), dt.time.min))
    return [{"id": j.id, "date": j.date, "action": j.action, "auteur": j.auteur} for j in db.scalars(q.limit(1000))]


class JournalSuppression(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


@router.post("/admin/journal/supprimer")
def journal_supprimer(b: JournalSuppression, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Supprime des entrées du journal (une ou plusieurs). La suppression elle-même est consignée."""
    res = db.execute(delete(JournalAction).where(JournalAction.id.in_(set(b.ids))))
    db.commit()
    n = res.rowcount or 0
    if n:
        log_action(db, f"Journal : {n} entrée(s) supprimée(s)", user)
    return {"supprimees": n}


def _cloisonnement(db: Session, pid: Optional[int] = None) -> dict:
    """Section 4.2 : aucune donnée d'un autre projet dans une synthèse, une recommandation ou une réponse du chat."""
    proj_de = {t["id"]: t["projet_id"] for t in crm.list_tickets()}
    verifies = violations = 0
    q = select(Projet).where(Projet.crm_projet_id.is_not(None))
    if pid:
        q = q.where(Projet.id == pid)
    for p in db.scalars(q):
        textes = [r.texte for r in db.scalars(select(Recommandation).where(Recommandation.id_projet == p.id))]
        textes += [c.reponse for c in db.scalars(select(ConversationChat).where(ConversationChat.id_projet == p.id))]
        textes += [s.contenu for s in db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == p.id)
                                                 .order_by(SyntheseSuivi.id.desc()).limit(20))]
        for txt in textes:
            verifies += 1
            if any(proj_de.get(int(x), p.crm_projet_id) != p.crm_projet_id for x in re.findall(r"T-0*(\d+)", txt)):
                violations += 1
    return {"textes_verifies": verifies, "violations": violations}


def _evaluation_suivi(db: Session, pid: Optional[int] = None) -> dict:
    """§4.2 : précision et rappel de l'anticipation (« à surveiller » → effectivement en retard), analyses déclenchées."""
    hist: dict[int, list[str]] = {}
    q = select(SuiviRetard).order_by(SuiviRetard.id_ticket, SuiviRetard.date_calcul, SuiviRetard.id)
    if pid:
        q = q.where(SuiviRetard.id_projet == pid)
    for s in db.scalars(q):
        h = hist.setdefault(s.id_ticket, [])
        if not h or h[-1] != s.situation:
            h.append(s.situation)
    signales = [h for h in hist.values() if "a_surveiller" in h]
    retards = [h for h in hist.values() if "en_retard" in h]
    signales_puis_retard = [h for h in signales if "en_retard" in h[h.index("a_surveiller"):]]
    retards_signales = [h for h in retards if "a_surveiller" in h[:h.index("en_retard")]]
    par: dict[str, int] = {"crm": 0, "temporel": 0, "autre": 0}
    total = 0
    qa = select(AnalyseTicket)
    if pid:
        qa = qa.where(AnalyseTicket.id_projet == pid)
    for a in db.scalars(qa):
        total += 1
        par["crm" if a.declencheur.startswith("crm") else "temporel" if a.declencheur.startswith("temporel") else "autre"] += 1
    return {"signales": len(signales), "retards": len(retards),
            "precision": len(signales_puis_retard) / len(signales) if signales else None,
            "rappel": len(retards_signales) / len(retards) if retards else None,
            "analyses": {"total": total, **par}}


@router.get("/evaluation")
def evaluation(projet_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Métriques du cahier des charges (section 4). Avec `projet_id`, elles ne portent que sur CE projet (cahier, tâches,
    recommandations, suivi) ; sans, sur l'ensemble de l'application."""
    projet = projects.get(db, projet_id) if projet_id else None
    # Seules les tâches d'un cahier VALIDÉ comptent : tant que le brouillon est en relecture, la décision n'est pas prise
    # (sinon les taux seraient faussés par des tâches « proposées » jamais jugées).
    ts = [t for t in db.scalars(select(Tache)) if t.origine == "agent" and t.cahier.statut in ("valide", "partiel")
          and (not projet or t.cahier.projet_id == projet.id)]
    n = len(ts) or 1
    cnt = lambda s: sum(t.statut_relecture == s for t in ts)
    gardees = [t for t in ts if t.statut_relecture in ("acceptee", "modifiee")]
    qr = select(Recommandation)
    if projet:
        qr = qr.where(Recommandation.id_projet == projet.id)
    recs = [r for r in db.scalars(qr) if not r.obsolete]
    rn = len(recs) or 1
    try:
        clo = _cloisonnement(db, projet.id if projet else None)
    except Exception:
        clo = {"textes_verifies": 0, "violations": 0}
    return {
        "projet": {"id": projet.id, "nom": projet.nom} if projet else None,
        "suivi": _evaluation_suivi(db, projet.id if projet else None),
        "taches": {"proposees": len(ts), "taux_acceptation_directe": cnt("acceptee") / n,
                   "taux_correction": cnt("modifiee") / n, "taux_rejet": cnt("supprimee") / n,
                   "ecart_duree_moyen": sum(abs(t.duree_estimee - t.duree_proposee) for t in gardees) / (len(gardees) or 1)},
        "recommandations": {"emises": len(recs), "taux_suivi": sum(r.decision == "suivie" for r in recs) / rn,
                            "taux_rejet": sum(r.decision == "rejetee" for r in recs) / rn,
                            "contenant_relance": sum("relanc" in r.texte.lower() for r in recs),
                            "repli_deterministe": sum(r.source == "fallback" for r in recs)},
        "cloisonnement": clo,
    }