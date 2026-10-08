import datetime as dt
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import agent, mailer, reports, service, settings_store
from . import tools as T
from .calendar_utils import add_bd
from .connector import connector as crm
from .db import SessionLocal, get_db
from .models import (AnalyseTicket, CahierDesCharges, ConversationChat, JournalAction, Notification, Projet, Rapport,
                     Recommandation, SyntheseSuivi, Tache, User)
from .security import create_token, current_admin, verify_password

public = APIRouter()
router = APIRouter(dependencies=[Depends(current_admin)])


def log_action(db: Session, action: str, auteur: str):
    db.add(JournalAction(action=action, auteur=auteur))
    db.commit()


# ---------------- Connexion ----------------
class Login(BaseModel):
    nom: str
    mot_de_passe: str


@public.post("/auth/login")
def login(b: Login, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.nom == b.nom)).first()
    if not u or not verify_password(b.mot_de_passe, u.password_hash):
        raise HTTPException(401, "Identifiants incorrects")
    return {"token": create_token(u.nom), "nom": u.nom}


# ---------------- Référentiels CRM (via le connecteur) ----------------
@router.get("/crm/projets")
def crm_projets(): return crm.projets()


@router.get("/crm/membres")
def crm_membres(): return crm.membres()


# ---------------- Création des tâches ----------------
def tache_out(t: Tache) -> dict:
    return {c: getattr(t, c) for c in (
        "id", "ordre", "titre", "description", "criteres_acceptation", "priorite", "raison_priorite", "duree_estimee",
        "depend_de", "source_dans_document", "niveau_confiance", "profil_recommande", "ambiguites", "membre_ids",
        "statut_relecture", "origine", "id_ticket_crm")} | {"echeance": t.date_echeance_initiale}


def cahier_out(c: CahierDesCharges) -> dict:
    return {"id": c.id, "statut": c.statut, "projet": c.projet.nom, "ambiguites": c.ambiguites,
            "taches": [tache_out(t) for t in c.taches if t.statut_relecture != "supprimee"]}


@router.post("/cahiers")
def deposer_cahier(projet_nom: str = Form(...), crm_projet_id: int = Form(...), texte: str = Form(""),
                   fichier: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
                   user: str = Depends(current_admin)):
    """Import (PDF, Word, texte) → extraction/nettoyage → agent → brouillon à relire."""
    nom = "texte saisi"
    if fichier and fichier.filename:
        suffix = Path(fichier.filename).suffix.lower()
        if suffix not in (".pdf", ".docx", ".txt", ".md"):
            raise HTTPException(400, "Formats acceptés : PDF, Word (.docx), texte")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(fichier.file.read())
        texte, nom = T.extract_text(f.name), fichier.filename
    else:
        texte = T.clean_text(texte)
    if len(texte) < 30:
        raise HTTPException(400, "Document vide ou illisible")
    ctx = {"tickets": crm.list_tickets(), "membres": crm.membres(), "profils": crm.profils()}
    try:
        res = agent.create_tasks(texte, ctx)
    except Exception as e:
        raise HTTPException(502, f"Modèle d'IA indisponible : {e}")
    if not res:
        raise HTTPException(502, "L'agent n'a pas produit de tâches exploitables. Réessayez ou changez de modèle.")
    p = Projet(nom=projet_nom, crm_projet_id=crm_projet_id)
    c = CahierDesCharges(projet=p, nom_fichier=nom, texte=texte, ambiguites=res["ambiguites_globales"])
    for t in res["taches"]:
        d = max(1, int(t["duree_estimee_jours"]))
        c.taches.append(Tache(
            ordre=t["id"], titre=t["titre"], description=t.get("description", ""),
            criteres_acceptation=t.get("criteres_acceptation") or [], priorite=t.get("priorite", "moyenne"),
            raison_priorite=t.get("raison_priorite", ""), duree_estimee=d, duree_proposee=d,
            depend_de=t.get("depend_de") or [], source_dans_document=t.get("source_dans_document", ""),
            niveau_confiance=t["niveau_confiance"], profil_recommande=t.get("profil_recommande", ""),
            ambiguites=t["ambiguites"], membre_ids=t["membre_ids_proposes"]))
    db.add(c)
    db.commit()
    log_action(db, f"Dépôt du cahier des charges « {nom} » : {len(c.taches)} tâches proposées", user)
    return cahier_out(c)


class TacheIn(BaseModel):
    titre: Optional[str] = None
    description: Optional[str] = None
    priorite: Optional[str] = None
    duree_estimee: Optional[int] = Field(None, ge=1)
    membre_ids: Optional[list[int]] = None
    depend_de: Optional[list[int]] = None


@router.get("/cahiers/{cid}")
def lire_cahier(cid: int, db: Session = Depends(get_db)):
    c = db.get(CahierDesCharges, cid)
    if not c:
        raise HTTPException(404)
    return cahier_out(c)


@router.put("/taches/{tid}")
def modifier_tache(tid: int, b: TacheIn, db: Session = Depends(get_db)):
    t = db.get(Tache, tid)
    if not t or t.id_ticket_crm:
        raise HTTPException(409, "Tâche introuvable ou déjà transmise au CRM")
    for k, v in b.model_dump(exclude_none=True).items():
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
    db.commit()
    return {"ok": True}


class NouvelleTache(BaseModel):
    titre: str
    description: str = ""
    priorite: str = "moyenne"
    duree_estimee: int = Field(1, ge=1)
    membre_ids: list[int] = []


@router.post("/cahiers/{cid}/taches")
def ajouter_tache(cid: int, b: NouvelleTache, db: Session = Depends(get_db)):
    c = db.get(CahierDesCharges, cid)
    if not c:
        raise HTTPException(404)
    t = Tache(cahier_id=cid, ordre=max([x.ordre for x in c.taches] + [0]) + 1, origine="manuel",
              statut_relecture="acceptee", modifiee_par_admin=True, duree_proposee=b.duree_estimee,
              **b.model_dump())
    db.add(t)
    db.commit()
    return tache_out(t)


@router.post("/cahiers/{cid}/valider")
def valider(cid: int, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Validation humaine → échéances (jours ouvrés) → création des tickets via le connecteur → e-mails."""
    c = db.get(CahierDesCharges, cid)
    if not c or c.statut == "valide":
        raise HTTPException(409, "Cahier introuvable ou déjà validé")
    taches = [t for t in c.taches if t.statut_relecture != "supprimee" and not t.id_ticket_crm]
    if not taches:
        raise HTTPException(400, "Aucune tâche à valider")
    dep = T.check_dependencies([{"id": t.ordre, "depend_de": t.depend_de} for t in taches])
    if not dep["ok"]:
        raise HTTPException(400, f"Dépendances invalides : {dep}")
    hol = settings_store.params(db)["holidays"]
    membres = {m["id"]: m for m in crm.membres()}
    par_ordre = {t.ordre: t for t in c.taches}
    today, erreurs, crees = dt.date.today(), [], 0
    for ordre in dep["ordre"]:                      # les tâches préalables sont créées en premier
        t = par_ordre[ordre]
        echeance = add_bd(today, t.duree_estimee, hol)
        try:
            res = crm.create_ticket({
                "titre": t.titre, "projet_id": c.projet.crm_projet_id, "echeance": str(echeance),
                "description": t.description + ("\n\nCritères d'acceptation :\n- " + "\n- ".join(t.criteres_acceptation)
                                                if t.criteres_acceptation else ""),
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
        for mid in t.membre_ids:                    # notification d'affectation (un échec n'annule pas la création)
            m = membres.get(mid)
            if not m:
                continue
            texte, statut = mailer.affectation_text(m["nom"], t.titre, res["id"], echeance), "envoye"
            try:
                mailer.send_assignment(m["email"], texte, t.titre)
            except Exception as e:
                statut = "echec"
                log_action(db, f"Échec d'envoi e-mail à {m['email']} : {e}", "système")
            db.add(Notification(id_tache=t.id, destinataire=m["email"], texte=texte, statut=statut))
        db.commit()
    c.statut = "valide" if not erreurs else "partiel"
    db.commit()
    log_action(db, f"Validation du cahier {cid} : {crees} ticket(s) créé(s) dans le CRM", user)
    return {"tickets_crees": crees, "erreurs": erreurs, "statut": c.statut}


# ---------------- Suivi : tableau de bord, analyse, synthèse ----------------
@router.get("/dashboard")
def dashboard():
    with SessionLocal() as db:
        tickets, tracking, _ = service.snapshot(db)
    projets = {p["id"]: p["nom"] for p in crm.projets()}
    return [{"id": i, "titre": t["titre"], "projet": projets.get(t["projet_id"], ""), "statut": t["statut"],
             "avancement_declare": t["avancement_declare"], "situation": tracking[i]["situation"],
             "etat_echeance": tracking[i]["libelle"], "echeance": t["echeance"],
             "motif": t.get("motif_retard_courant") or t.get("motif_attente_courant")}
            for i, t in tickets.items()]


@router.get("/tickets/{tid}/analyse")
def analyse(tid: int, db: Session = Depends(get_db)):
    try:
        t = crm.get_ticket(tid)
    except Exception:
        raise HTTPException(404, "Ticket introuvable")
    tickets, tracking, _ = service.snapshot(db)
    a = db.scalars(select(AnalyseTicket).where(AnalyseTicket.id_ticket == tid).order_by(AnalyseTicket.id.desc())).first()
    recos = db.scalars(select(Recommandation).where(Recommandation.id_ticket == tid).order_by(Recommandation.id.desc())
                       .limit(5)).all()
    return {"ticket": t, "calculs": tracking[tid], "historique": crm.historique(tid),
            "membres": crm.membres_du_ticket(tid), "bloque": [i for i, o in tickets.items() if tid in o["depend_de_ids"]],
            "analyse": a.contenu if a else None, "analyse_date": a.date if a else None,
            "recommandations": [{"id": r.id, "texte": r.texte, "date": r.date, "decision": r.decision} for r in recos]}


@router.get("/synthese")
def synthese(db: Session = Depends(get_db)):
    s = db.scalars(select(SyntheseSuivi).order_by(SyntheseSuivi.id.desc())).first()
    if not s:
        return None
    recos = db.scalars(select(Recommandation).where(Recommandation.decision.is_(None))
                       .order_by(Recommandation.id.desc()).limit(30)).all()
    vues, ouvertes = set(), []
    for r in recos:                                  # une recommandation en attente de décision par ticket
        if r.id_ticket not in vues:
            vues.add(r.id_ticket)
            ouvertes.append({"id": r.id, "texte": r.texte, "date": r.date})
    ch = s.chiffres
    return {"id": s.id, "date": s.date, "declencheur": s.declencheur, "contenu": s.contenu,
            "nb_en_retard": len(ch.get("en_retard", [])), "nb_a_surveiller": len(ch.get("a_surveiller", [])),
            "nb_en_attente": len(ch.get("en_attente", [])), "evolutions": ch.get("evolutions", []),
            "recommandations": ouvertes}


@router.post("/synthese/actualiser")
def actualiser(bg: BackgroundTasks):
    bg.add_task(service.reevaluate, set(), "manuel")
    return {"ok": True}


class Decision(BaseModel):
    decision: str = Field(pattern="^(suivie|rejetee)$")


@router.post("/recommandations/{rid}/decision")
def decider(rid: int, b: Decision, db: Session = Depends(get_db), user: str = Depends(current_admin)):
    """Suivre ou rejeter uniquement : une recommandation ne se modifie pas."""
    r = db.get(Recommandation, rid)
    if not r:
        raise HTTPException(404)
    r.decision = b.decision
    db.commit()
    log_action(db, f"Recommandation {rid} (T-{r.id_ticket:03d}) : {b.decision}", user)
    return {"ok": True}


class EcheanceIn(BaseModel):
    nouvelle_date: dt.date
    motif: str = Field(min_length=3)


@router.put("/tickets/{tid}/echeance")
def modifier_echeance(tid: int, b: EcheanceIn, bg: BackgroundTasks, db: Session = Depends(get_db),
                      user: str = Depends(current_admin)):
    """Décision humaine : seul chemin d'écriture de l'échéance, tracé au journal."""
    ancienne = crm.get_ticket(tid)["echeance"]
    crm.set_echeance(tid, b.nouvelle_date)
    log_action(db, f"Échéance T-{tid:03d} : {ancienne} → {b.nouvelle_date}. Motif : {b.motif}", user)
    bg.add_task(service.reevaluate, {tid}, "modification de l'échéance")
    return {"ok": True}


class ChatIn(BaseModel):
    question: str = Field(min_length=2)


@router.post("/chat")
def chat(b: ChatIn, db: Session = Depends(get_db)):
    rep = service.chat(b.question)
    db.add(ConversationChat(question=b.question, reponse=rep))
    db.commit()
    return {"reponse": rep}


# ---------------- Rapports (bonus) ----------------
def _rapport(fmt: str, db: Session):
    tickets, tracking, _ = service.snapshot(db)
    s = db.scalars(select(SyntheseSuivi).order_by(SyntheseSuivi.id.desc())).first()
    texte = s.contenu if s else "Aucune synthèse disponible."
    db.add(Rapport(format=fmt, contenu=texte))
    db.commit()
    return reports.pdf(texte, tickets, tracking) if fmt == "pdf" else reports.xlsx(texte, tickets, tracking)


@router.get("/rapports/pdf")
def rapport_pdf(db: Session = Depends(get_db)):
    return Response(_rapport("pdf", db), media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=rapport_suivi.pdf"})


@router.get("/rapports/xlsx")
def rapport_xlsx(db: Session = Depends(get_db)):
    return Response(_rapport("xlsx", db),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=rapport_suivi.xlsx"})


# ---------------- Administration (bonus) et évaluation ----------------
class AdminSettings(BaseModel):
    seuil_jours: int = Field(ge=0)
    seuil_avancement: int = Field(ge=0, le=100)
    jours_feries: list[str]
    llm_model: str


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
    for k, v in b.model_dump().items():
        settings_store.put(db, k, v)
    log_action(db, f"Paramètres modifiés : {b.model_dump()}", user)
    return {"ok": True}


@router.get("/admin/journal")
def journal(db: Session = Depends(get_db)):
    return [{"date": j.date, "action": j.action, "auteur": j.auteur}
            for j in db.scalars(select(JournalAction).order_by(JournalAction.id.desc()).limit(200))]


@router.get("/evaluation")
def evaluation(db: Session = Depends(get_db)):
    """Métriques du cahier des charges (section 4)."""
    ts = [t for t in db.scalars(select(Tache)) if t.origine == "agent"]
    n = len(ts) or 1
    cnt = lambda s: sum(t.statut_relecture == s for t in ts)
    gardees = [t for t in ts if t.statut_relecture in ("acceptee", "modifiee")]
    recs = list(db.scalars(select(Recommandation)))
    rn = len(recs) or 1
    return {
        "taches": {"proposees": len(ts), "taux_acceptation_directe": cnt("acceptee") / n,
                   "taux_correction": cnt("modifiee") / n, "taux_rejet": cnt("supprimee") / n,
                   "ecart_duree_moyen": sum(abs(t.duree_estimee - t.duree_proposee) for t in gardees) / (len(gardees) or 1)},
        "recommandations": {"emises": len(recs), "taux_suivi": sum(r.decision == "suivie" for r in recs) / rn,
                            "taux_rejet": sum(r.decision == "rejetee" for r in recs) / rn,
                            "contenant_relance": sum("relanc" in r.texte.lower() for r in recs),
                            "repli_deterministe": sum(r.source == "fallback" for r in recs)},
    }
