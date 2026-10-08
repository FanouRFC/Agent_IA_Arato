"""Orchestration du suivi dynamique (boucle B) : détection → collecte → calculs Python → agent → actualisation.
Déclenché par les événements CRM (lecture du flux de changements) et par les événements temporels (scheduler)."""
import datetime as dt
import logging
import threading

from sqlalchemy import select

from . import agent, settings_store
from . import tools as T
from .connector import connector as crm
from .db import SessionLocal
from .models import AnalyseTicket, Recommandation, SuiviRetard, SyntheseSuivi

log = logging.getLogger("suivi")
_lock = threading.RLock()


def snapshot(db):
    """Données CRM actualisées + calculs déterministes pour tous les tickets."""
    p = settings_store.params(db)
    now = dt.datetime.now()
    tickets = {t["id"]: t for t in crm.list_tickets()}
    tracking = {i: T.compute_tracking(t, now, p["holidays"], p["seuil_jours"], p["seuil_avancement"], p["work_end"])
                for i, t in tickets.items()}
    return tickets, tracking, p


def _related(t, tickets, tracking):
    def info(i):
        tr = tracking.get(i)
        return {"id": i, "titre": tickets[i]["titre"], "statut": tickets[i]["statut"],
                "situation": tr["situation"] if tr else "?", "jours_retard": tr["jours_retard"] if tr else 0}
    return {"depend_de": [info(i) for i in t["depend_de_ids"] if i in tickets],
            "bloque": [info(i) for i, o in tickets.items() if t["id"] in o["depend_de_ids"]]}


def _dependents(ids: set[int], tickets) -> set[int]:
    return {i for i, o in tickets.items() if set(o["depend_de_ids"]) & ids and o["statut"] != "ferme"}


def reevaluate(ids: set[int], declencheur: str, llm_for_all: bool = False):
    """Réévaluation des tickets concernés (et des tickets dépendants)."""
    with _lock, SessionLocal() as db:
        tickets, tracking, _ = snapshot(db)
        # 1. Indicateur est_en_retard : calculé par Python, écrit par le backend via le connecteur
        for i, tr in tracking.items():
            if tickets[i]["est_en_retard"] != tr["est_en_retard"]:
                crm.set_est_en_retard(i, tr["est_en_retard"])
        concerned = {i for i in (ids | _dependents(ids, tickets)) if i in tickets}
        # 2-5. Suivi, enquête, analyse et recommandation (LLM uniquement si l'événement est pertinent)
        for i in concerned:
            t, tr = tickets[i], tracking[i]
            db.add(SuiviRetard(id_ticket=i, est_en_retard=tr["est_en_retard"], jours_de_retard=tr["jours_retard"],
                               retard_final=tr["retard_final"], situation=tr["situation"]))
            pertinent = llm_for_all or declencheur.startswith("crm") or tr["situation"] in ("a_surveiller", "en_retard") \
                or t["statut"] == "en_attente"
            if tr["situation"] == "ferme" or not pertinent:
                continue
            try:
                res = agent.analyse_ticket(t, tr, crm.historique(i), _related(t, tickets, tracking), crm.historique)
            except Exception as e:
                log.error("Analyse T-%s impossible : %s", i, e)
                continue
            db.add(AnalyseTicket(id_ticket=i, declencheur=declencheur, contenu=res))
            if res.get("recommandation"):
                db.add(Recommandation(id_ticket=i, type=tr["situation"], texte=res["recommandation"], chiffres=tr,
                                      diagnostic=res.get("diagnostic") or "", source=res["source"]))
        db.commit()
        # 6. Actualisation de la synthèse dynamique
        _update_synthese(db, tickets, tracking, declencheur)


def _update_synthese(db, tickets, tracking, declencheur):
    prev = db.scalars(select(SyntheseSuivi).order_by(SyntheseSuivi.id.desc()).limit(1)).first()
    prev_t = (prev.chiffres.get("par_ticket") if prev else None) or {}
    evolutions = []
    for i, tr in tracking.items():
        old = prev_t.get(str(i))
        if not old:
            continue
        if tr["situation"] == "en_retard" and old["situation"] != "en_retard":
            evolutions.append(f"T-{i:03d} est passée en retard.")
        elif tr["situation"] == "en_retard" and tr["jours_retard"] != old["jours_retard"]:
            evolutions.append(f"T-{i:03d} : le retard est passé de {old['jours_retard']} à {tr['jours_retard']} jour(s).")
        elif tr["situation"] == "a_surveiller" and old["situation"] == "normale":
            evolutions.append(f"T-{i:03d} est désormais à surveiller.")
        elif tr["situation"] == "ferme" and old["situation"] != "ferme":
            evolutions.append(f"T-{i:03d} a été fermée.")
        elif old.get("avancement") is not None and old["avancement"] != tr["avancement"] and tr["situation"] != "ferme":
            evolutions.append(f"T-{i:03d} : l'avancement déclaré est passé de {old['avancement']} % à {tr['avancement']} %.")

    def motif(i):
        return tickets[i].get("motif_retard_courant") or tickets[i].get("motif_attente_courant")

    faits = {
        "en_retard": [{"id": i, "jours_retard": tr["jours_retard"], "avancement": tr["avancement"], "motif": motif(i)}
                      for i, tr in tracking.items() if tr["situation"] == "en_retard"],
        "a_surveiller": [{"id": i, "jours_restants": tr["jours_restants"], "avancement": tr["avancement"]}
                         for i, tr in tracking.items() if tr["situation"] == "a_surveiller"],
        "en_attente": [{"id": i, "motif": motif(i)} for i, t in tickets.items() if t["statut"] == "en_attente"],
        "evolutions": evolutions,
    }
    texte = agent.synthese_narrative(faits)
    chiffres = {**faits, "par_ticket": {str(i): {"situation": tr["situation"], "jours_retard": tr["jours_retard"],
                                                 "avancement": tr["avancement"]} for i, tr in tracking.items()}}
    db.add(SyntheseSuivi(declencheur=declencheur, contenu=texte, chiffres=chiffres))
    db.commit()


# ---------- A. Suivi événementiel : flux de changements du CRM ----------
def poll_crm_events():
    try:
        with SessionLocal() as db:
            cursor = settings_store.get(db, "crm_cursor", 0)
        events = crm.evenements(cursor)
        if not events:
            return
        ids = {e["ticket_id"] for e in events if e["source"] == "crm" and e["ticket_id"]}
        if ids:
            types = sorted({e["type"] for e in events if e["source"] == "crm"})
            reevaluate(ids, "crm: " + ", ".join(types))
        with SessionLocal() as db:
            settings_store.put(db, "crm_cursor", max(e["id"] for e in events))
    except Exception as e:
        log.warning("Lecture des événements CRM impossible : %s", e)


# ---------- B. Suivi temporel : le passage du temps change la situation d'une tâche ----------
def temporal_check():
    """Compare la situation calculée à la dernière connue ; réévalue seulement s'il y a changement
    (échéance atteinte/dépassée, jours de retard, seuil « à surveiller »). Le LLM n'est pas appelé en permanence.
    Exécuté sous verrou : la comparaison porte toujours sur l'état à jour (pas de course avec le suivi événementiel)."""
    try:
        with _lock, SessionLocal() as db:
            tickets, tracking, _ = snapshot(db)
            # Resynchronisation de l'indicateur (calculé par Python) si le CRM diverge : aucun appel au LLM
            for i, tr in tracking.items():
                if tickets[i]["est_en_retard"] != tr["est_en_retard"]:
                    crm.set_est_en_retard(i, tr["est_en_retard"])
            last = {s.id_ticket: s for s in db.scalars(
                select(SuiviRetard).distinct(SuiviRetard.id_ticket).order_by(SuiviRetard.id_ticket,
                                                                              SuiviRetard.date_calcul.desc()))}
            changed = {i for i, tr in tracking.items()
                       if i not in last or last[i].situation != tr["situation"]
                       or last[i].jours_de_retard != tr["jours_retard"]}
            if changed:
                reevaluate(changed, "temporel: échéance ou seuil atteint")
    except Exception as e:
        log.warning("Contrôle temporel impossible : %s", e)


def chat(question: str) -> str:
    with SessionLocal() as db:
        tickets, tracking, _ = snapshot(db)
    return agent.chat_answer(question, tickets, tracking, crm.historique)
