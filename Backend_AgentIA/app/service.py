"""Orchestration du suivi dynamique (boucle B), PROJET PAR PROJET :
détection → collecte → calculs Python → agent → actualisation de la synthèse du projet concerné.
Déclenché par les événements CRM (flux de changements) et par les événements temporels (scheduler).
Aucune donnée d'un projet n'est jamais fournie à l'agent pour l'analyse d'un autre projet (2.6)."""
import datetime as dt
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from . import agent, llm, projects, settings_store
from . import tools as T
from .connector import connector as crm
from .db import SessionLocal
from .models import AnalyseTicket, Projet, Recommandation, SuiviRetard, SyntheseSuivi, Tache, ValidationCritere

log = logging.getLogger("suivi")
FORMAT_SYNTHESE = 2      # incrémenté quand la rédaction de la synthèse change : les anciennes sont régénérées automatiquement
STATUT_LIB = {"nouveau": "Nouveau", "ouvert": "Ouvert", "en_cours": "En cours", "en_attente": "En attente", "ferme": "Fermé"}


def _fr(iso: str) -> str:
    try:
        return dt.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)
_lock = threading.RLock()
_derniers_avertissements: dict[str, float] = {}


def _avertir_limite(cle: str, message: str, *args, toutes_les: float = 300.0):
    """Journalise un avertissement répétitif (CRM injoignable…) au plus une fois toutes les `toutes_les` secondes : les boucles du
    scheduler tournent toutes les 2 s / 60 s, une panne ne doit pas inonder le journal. Le retour à la normale est signalé."""
    import time
    maintenant = time.monotonic()
    if maintenant - _derniers_avertissements.get(cle, -1e9) >= toutes_les:
        _derniers_avertissements[cle] = maintenant
        log.warning(message, *args)


def _retablir(cle: str, message: str):
    if _derniers_avertissements.pop(cle, None) is not None:
        log.info(message)
# Les appels au modèle d'IA sont lents (limite de débit) : ils s'exécutent dans un fil dédié, un par un, SANS bloquer la
# mise à jour immédiate de la situation, des recommandations et des prévisions (phase rapide, calculée par Python).
_llm_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-llm")


def _phrase_ajouts(nouvelles: list[tuple[int, str]]) -> str:
    """« T-039 « … » a été ajoutée au projet. » ou « T-039, T-040 et T-041 ont été ajoutées au projet : « … », « … ». »"""
    if len(nouvelles) == 1:
        i, titre = nouvelles[0]
        return f"T-{i:03d} « {titre} » a été ajoutée au projet."
    ids = [f"T-{i:03d}" for i, _ in nouvelles]
    liste = ", ".join(ids[:-1]) + " et " + ids[-1]
    if len(nouvelles) <= 5:
        return f"{liste} ont été ajoutées au projet : " + ", ".join(f"« {t} »" for _, t in nouvelles) + "."
    return f"{liste} ont été ajoutées au projet."


def snapshot(db, projet: Projet):
    """Données CRM actualisées + calculs déterministes, pour les seuls tickets du projet."""
    p = settings_store.params(db)
    now = dt.datetime.now()
    tickets = {t["id"]: t for t in crm.list_tickets(projet_id=projet.crm_projet_id)}
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


def _sync_indicateur(tickets, tracking):
    """est_en_retard : calculé par Python, écrit par le backend via le connecteur (jamais par l'agent)."""
    for i, tr in tracking.items():
        if tickets[i]["est_en_retard"] != tr["est_en_retard"]:
            crm.set_est_en_retard(i, tr["est_en_retard"])


def reevaluate(projet_id: int, ids: set[int], declencheur: str):
    """Réévaluation des tickets concernés (et des tickets dépendants) d'UN projet, puis de sa synthèse, en DEUX phases :
    1. phase rapide (immédiate) : analyses, recommandations, prévisions et synthèse calculées par Python seul → la page
       « Situation du projet » reflète le CRM en quelques secondes ;
    2. phase IA (en arrière-plan) : le modèle affine analyses, recommandations et synthèse, sans jamais retarder la phase 1."""
    debut = dt.datetime.now()
    concerned = _phase_rapide(projet_id, ids, declencheur)
    if concerned:
        _llm_pool.submit(_phase_ia, projet_id, concerned, declencheur, debut)


def _pertinent(declencheur: str, t: dict, tr: dict) -> bool:
    return declencheur.startswith("crm") or declencheur == "modification de l'échéance" \
        or tr["situation"] in ("a_surveiller", "en_retard") or t["statut"] == "en_attente" \
        or bool(tr.get("cloture_a_valider"))       # 100 % déclaré, clôture non validée : à signaler au haut responsable


def _phase_rapide(projet_id: int, ids: set[int], declencheur: str) -> set[int]:
    with _lock, SessionLocal() as db:
        projet = projects.get(db, projet_id)
        tickets, tracking, _ = snapshot(db, projet)
        _sync_indicateur(tickets, tracking)
        concerned = {i for i in (ids | _dependents(ids, tickets)) if i in tickets}
        for i in sorted(concerned):
            t, tr = tickets[i], tracking[i]
            db.add(SuiviRetard(id_projet=projet.id, id_ticket=i, est_en_retard=tr["est_en_retard"],
                               jours_de_retard=tr["jours_retard"], retard_final=tr["retard_final"], situation=tr["situation"]))
            try:
                res = agent.analyse_simple(t, tr, crm.historique(i), _related(t, tickets, tracking))
            except Exception as e:
                log.error("Analyse rapide T-%s impossible (%s)", i, e)
                try:     # aucun ticket ne doit rester sans analyse : ce repli ne dépend ni du LLM ni de l'historique
                    res = agent.analyse_simple(t, tr, {"statuts": [], "avancements": []})
                except Exception as e2:
                    log.error("Repli T-%s impossible : %s", i, e2)
                    continue
            if tr["situation"] == "ferme" or not _pertinent(declencheur, t, tr):
                _clore_reco(db, i)             # plus rien à recommander : la recommandation ouverte disparaît
            res = {**res, "repere": _repere(t, tr)}
            db.add(AnalyseTicket(id_projet=projet.id, id_ticket=i, declencheur=declencheur, contenu=res))
            if tr["situation"] != "ferme" and _pertinent(declencheur, t, tr):
                _enregistrer_reco(db, projet, i, tr, res)
        db.commit()
        _update_synthese(db, projet, tickets, tracking, declencheur, avec_llm=False)
        return {i for i in concerned if tracking[i]["situation"] != "ferme" and _pertinent(declencheur, tickets[i], tracking[i])}


def _phase_ia(projet_id: int, concerned: set[int], declencheur: str, debut: dt.datetime):
    """Affinage par le modèle d'IA. Un résultat devenu obsolète (le ticket a changé entre-temps) est ignoré : le nouvel
    événement a déjà déclenché sa propre réévaluation."""
    try:
        with SessionLocal() as db:
            projet = projects.get(db, projet_id)
            tickets, tracking, _ = snapshot(db, projet)

        def historique_du_projet(i: int):      # cloisonnement : l'agent ne lit que des tickets du projet courant
            if i not in tickets:
                raise ValueError("Ticket absent du projet courant")
            return crm.historique(i)

        resultats = {}
        for i in sorted(concerned):
            if i not in tickets or tracking[i]["situation"] == "ferme":
                continue
            t, tr = tickets[i], tracking[i]
            try:
                res = agent.analyse_ticket(t, tr, crm.historique(i), _related(t, tickets, tracking), historique_du_projet)
            except Exception as e:
                log.warning("Analyse IA de T-%s impossible (%s) : l'analyse rapide est conservée", i, e)
                continue
            if res.get("source") == "llm":
                resultats[i] = (res, _repere(t, tr))
        with _lock, SessionLocal() as db:
            projet = projects.get(db, projet_id)
            tickets, tracking, _ = snapshot(db, projet)
            for i, (res, repere) in resultats.items():
                if i not in tickets or _repere(tickets[i], tracking[i]) != repere:
                    continue                    # le ticket a changé depuis : résultat périmé
                db.add(AnalyseTicket(id_projet=projet.id, id_ticket=i, declencheur=declencheur,
                                     contenu={**res, "repere": repere}))
                _enregistrer_reco(db, projet, i, tracking[i], res, depuis=debut)
            db.commit()
        # La synthèse rédigée par le modèle est préparée SANS tenir le verrou : une mise à jour du CRM (échéance, statut…)
        # n'attend jamais l'IA. Avant d'être enregistrée, elle est revérifiée contre l'état réel (voir _update_synthese).
        with SessionLocal() as db:
            projet = projects.get(db, projet_id)
            tickets, tracking, _ = snapshot(db, projet)
            _update_synthese(db, projet, tickets, tracking, declencheur, avec_llm=True)
    except Exception as e:
        log.warning("Phase IA du suivi interrompue (la situation reste à jour grâce à la phase rapide) : %s", e)


def couverture(db, pid: int, tickets: dict, tracking: dict) -> dict:
    """Preuve de suivi : chaque ticket du projet doit avoir une analyse à jour. `en_cours` = tickets dont l'analyse
    est absente ou plus ancienne que l'état réel (une réévaluation est alors imminente)."""
    ana = {a.id_ticket: (a.contenu or {}).get("repere") or {} for a in db.scalars(
        select(AnalyseTicket).where(AnalyseTicket.id_projet == pid)
        .distinct(AnalyseTicket.id_ticket).order_by(AnalyseTicket.id_ticket, AnalyseTicket.id.desc()))}
    en_cours = []
    for i, t in tickets.items():
        if tracking[i]["situation"] == "ferme":       # un ticket fermé n'a plus rien à suivre
            continue
        if not ana.get(i) or ana[i] != _repere(t, tracking[i]):
            en_cours.append(i)
    return {"total": len(tickets), "a_jour": len(tickets) - len(en_cours), "en_cours": sorted(en_cours)}


def _repere(t, tr) -> dict:
    """État du ticket au moment de l'analyse : sert à détecter qu'il a changé (événement CRM ou simple passage du temps)."""
    return {"statut": t["statut"], "situation": tr["situation"], "jours_retard": tr["jours_retard"],
            "jours_restants": tr["jours_restants"], "avancement": tr["avancement"], "echeance": tr["echeance"],
            "motif": t.get("motif_retard_courant") or t.get("motif_attente_courant") or ""}


def reevaluate_all(projet_id: int, declencheur: str = "automatique"):
    """Évaluation complète d'un projet (tous les tickets non fermés), lancée automatiquement, jamais à la main."""
    with SessionLocal() as db:
        tickets, _, _ = snapshot(db, projects.get(db, projet_id))
    reevaluate(projet_id, {i for i, t in tickets.items() if t["statut"] != "ferme"}, declencheur)


def _clore_reco(db, tid: int):
    for r in db.scalars(select(Recommandation).where(Recommandation.id_ticket == tid, Recommandation.decision.is_(None),
                                                     Recommandation.obsolete.is_(False))):
        r.obsolete = True


def _enregistrer_reco(db, projet: Projet, tid: int, tr: dict, res: dict, depuis: dt.datetime | None = None):
    """Une seule recommandation ouverte par ticket : une nouvelle remplace l'ancienne non décidée.
    `depuis` : début de la réévaluation en cours ; si le responsable a déjà tranché une recommandation créée depuis,
    l'affinage du modèle ne la re-propose pas."""
    texte = res.get("recommandation")
    if not texte:
        _clore_reco(db, tid)
        return
    derniere = db.scalars(select(Recommandation).where(Recommandation.id_ticket == tid, Recommandation.obsolete.is_(False))
                          .order_by(Recommandation.id.desc())).first()
    if derniere and derniere.texte == texte:
        return
    if derniere and derniere.decision and depuis and derniere.date >= depuis:
        return
    _clore_reco(db, tid)
    db.add(Recommandation(id_projet=projet.id, id_ticket=tid, type=tr["situation"], texte=texte, chiffres=tr,
                          diagnostic=res.get("diagnostic") or "", source=res["source"]))


def _update_synthese(db, projet: Projet, tickets, tracking, declencheur, avec_llm: bool = True):
    prev = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == projet.id)
                      .order_by(SyntheseSuivi.id.desc()).limit(1)).first()
    prev_t = (prev.chiffres.get("par_ticket") if prev else None) or {}
    evolutions = []
    if prev:
        def lib(st):
            return STATUT_LIB.get(st, st)
        # Toutes les tâches apparues depuis la dernière analyse sont regroupées en UNE phrase, dans l'ordre des numéros :
        # aucune (ex. T-039) ne peut être omise quand plusieurs sont créées en même temps.
        nouvelles = sorted(i for i in tracking if not prev_t.get(str(i)))
        if nouvelles:
            evolutions.append(_phrase_ajouts([(i, tickets[i]["titre"]) for i in nouvelles]))
        for i, tr in tracking.items():
            old, t = prev_t.get(str(i)), tickets[i]
            if not old:
                continue
            m = t.get("motif_retard_courant") or t.get("motif_attente_courant") or ""
            if t["statut"] != old.get("statut", t["statut"]):
                evolutions.append(f"T-{i:03d} : le statut est passé de « {lib(old['statut'])} » à « {lib(t['statut'])} ».")
            if tr["situation"] == "en_retard" and old["situation"] != "en_retard":
                evolutions.append(f"T-{i:03d} est passée en retard.")
            elif tr["situation"] == "en_retard" and tr["jours_retard"] != old["jours_retard"]:
                evolutions.append(f"T-{i:03d} : le retard est passé de {old['jours_retard']} à {tr['jours_retard']} jour(s).")
            elif tr["situation"] == "a_surveiller" and old["situation"] == "normale":
                evolutions.append(f"T-{i:03d} est désormais à surveiller.")
            elif tr["situation"] == "normale" and old["situation"] in ("en_retard", "a_surveiller"):
                evolutions.append(f"T-{i:03d} est revenue dans les délais.")
            if old.get("avancement") is not None and old["avancement"] != tr["avancement"] and tr["situation"] != "ferme":
                evolutions.append(f"T-{i:03d} : l'avancement déclaré est passé de {old['avancement']} % à {tr['avancement']} %.")
            if old.get("echeance") and old["echeance"] != tr["echeance"]:
                evolutions.append(f"T-{i:03d} : l'échéance a été déplacée du {_fr(old['echeance'])} au {_fr(tr['echeance'])}.")
            if m and m != old.get("motif", ""):
                evolutions.append(f"T-{i:03d} : un motif a été documenté (« {m} »).")
        for k in prev_t:
            if k.isdigit() and int(k) not in tickets:
                evolutions.append(f"T-{int(k):03d} n'existe plus dans le CRM.")

    blocks = T.blocked_map(tickets)

    def motif(i):
        return tickets[i].get("motif_retard_courant") or tickets[i].get("motif_attente_courant")

    # Nombre de mises en attente successives, pour les seules tâches susceptibles d'être prioritaires
    candidats = [i for i, tr in tracking.items() if tr["situation"] in ("en_retard", "a_surveiller")
                 or tickets[i]["statut"] == "en_attente"][:60]
    nb_bl = {}
    for i in candidats:
        try:
            nb_bl[i] = T.history_facts(crm.historique(i))["nb_blocages"]
        except Exception:
            pass
    priorites = T.prioritize(tickets, tracking, blocks, nb_bl, limit=10)

    # Risques et prédictions : dernière analyse de chaque ticket non fermé du projet
    risques = []
    for i, tr in tracking.items():
        if tr["situation"] == "ferme":
            continue
        a = db.scalars(select(AnalyseTicket).where(AnalyseTicket.id_ticket == i, AnalyseTicket.id_projet == projet.id)
                       .order_by(AnalyseTicket.id.desc())).first()
        if a and a.contenu.get("risque") in ("eleve", "modere"):
            risques.append({"id": i, "risque": a.contenu["risque"], "prediction": a.contenu.get("prediction") or ""})
    risques.sort(key=lambda r: (r["risque"] != "eleve", r["id"]))

    # Catégories EXCLUSIVES : une tâche n'est comptée qu'une seule fois (retard > à surveiller > en attente), et les tâches
    # terminées sont comptées à part. Elles reflètent exactement l'état réel du CRM (pas de tâche fermée « en attente »).
    faits = {
        "projet": projet.nom,
        "total": len(tickets),
        "en_retard": [{"id": i, "jours_retard": tr["jours_retard"], "avancement": tr["avancement"], "motif": motif(i)}
                      for i, tr in tracking.items() if tr["situation"] == "en_retard"],
        "a_surveiller": [{"id": i, "jours_restants": tr["jours_restants"], "avancement": tr["avancement"]}
                         for i, tr in tracking.items() if tr["situation"] == "a_surveiller"],
        "en_attente": [{"id": i, "motif": motif(i)} for i, t in tickets.items()
                       if t["statut"] == "en_attente" and tracking[i]["situation"] not in ("en_retard", "a_surveiller", "ferme")],
        "termine": [i for i, tr in tracking.items() if tr["situation"] == "ferme"],
        "priorites": priorites,
        "risques": risques,
        "evolutions": evolutions,
    }
    # Mémoire des évolutions : un événement CRM et le contrôle temporel peuvent s'enchaîner à quelques secondes d'écart ;
    # la seconde analyse ne doit pas effacer ce que la première vient de constater. On garde donc 24 h d'évolutions.
    maintenant = dt.datetime.now()
    recent = []
    for e in (prev.chiffres.get("evolutions_hist") if prev else None) or []:
        try:
            if maintenant - dt.datetime.fromisoformat(e["t"]) < dt.timedelta(hours=24):
                recent.append(e)
        except (KeyError, ValueError, TypeError):
            pass
    nouvelles = [{"t": maintenant.isoformat(timespec="seconds"), "txt": e} for e in evolutions]
    hist_evo = (nouvelles + [e for e in recent if e["txt"] not in {n["txt"] for n in nouvelles}])[:40]
    if not evolutions:
        # La phase rapide a déjà constaté le changement : la rédaction affinée par l'IA doit le citer aussi (90 s de mémoire).
        faits["evolutions"] = [e["txt"] for e in hist_evo
                               if (maintenant - dt.datetime.fromisoformat(e["t"])).total_seconds() < 90]
    texte, source = agent.synthese_deterministe(faits), "fallback"
    if avec_llm:
        narratif = agent.synthese_narrative(faits)       # appel lent : le verrou n'est PAS tenu pendant la rédaction
        with _lock:
            tickets2, tracking2, _ = snapshot(db, projet)
            courante = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == projet.id)
                                  .order_by(SyntheseSuivi.id.desc()).limit(1)).first()
            if _etat(tickets2, tracking2) != _etat(tickets, tracking) or (courante.id if courante else None) != (prev.id if prev else None):
                log.info("Synthèse IA abandonnée (projet %s) : l'état du projet a changé pendant la rédaction", projet.nom)
                return                                    # périmée : la mise à jour qui a suivi a déjà produit la bonne
            texte, source = narratif
            _ecrire_synthese(db, projet, tickets, tracking, declencheur, faits, texte, source, hist_evo)
        return
    _ecrire_synthese(db, projet, tickets, tracking, declencheur, faits, texte, source, hist_evo)


def _etat(tickets, tracking) -> dict:
    """Empreinte de l'état réel d'un projet (statuts, échéances, avancements, situations, motifs)."""
    return {i: _repere(t, tracking[i]) for i, t in tickets.items()}


def _ecrire_synthese(db, projet, tickets, tracking, declencheur, faits, texte, source, hist_evo):
    chiffres = {**faits, "v": FORMAT_SYNTHESE, "source": source, "evolutions_hist": hist_evo,
                "par_ticket": {str(i): {"situation": tr["situation"], "jours_retard": tr["jours_retard"],
                                        "avancement": tr["avancement"], "statut": tickets[i]["statut"],
                                        "echeance": tr["echeance"], "jours_restants": tr["jours_restants"],
                                        "motif": tickets[i].get("motif_retard_courant")
                                        or tickets[i].get("motif_attente_courant") or ""}
                                    for i, tr in tracking.items()}}
    db.add(SyntheseSuivi(id_projet=projet.id, declencheur=declencheur, contenu=texte, chiffres=chiffres))
    db.commit()


# ---------- Cohérence immédiate : la situation affichée correspond TOUJOURS à l'état réel du CRM ----------
def _vue_ticket(t, tr) -> dict:
    return {"situation": tr["situation"], "jours_retard": tr["jours_retard"], "avancement": tr["avancement"],
            "statut": t["statut"], "echeance": tr["echeance"], "jours_restants": tr["jours_restants"],
            "motif": t.get("motif_retard_courant") or t.get("motif_attente_courant") or ""}


def ecarts(chiffres: dict, tickets: dict, tracking: dict) -> tuple[set[int], str]:
    """Tickets dont l'état réel diffère de celui sur lequel repose la dernière synthèse (échéance déplacée, statut changé,
    jour passé…), et la nature du changement (déclencheur). Retourne (ensemble vide, "") si la synthèse est à jour."""
    ancien = (chiffres or {}).get("par_ticket") or {}
    ids, champs = set(), set()
    for i, t in tickets.items():
        a, n = ancien.get(str(i)), _vue_ticket(t, tracking[i])
        if a is None:
            ids.add(i)
            champs.add("nouveau")
            continue
        diff = {k for k in n if a.get(k) != n[k]}
        if diff:
            ids.add(i)
            champs |= diff
    if any(k.isdigit() and int(k) not in tickets for k in ancien):
        champs.add("supprime")
    if (chiffres or {}).get("v") != FORMAT_SYNTHESE:
        champs.add("format")
    if not champs:
        return set(), ""
    donnees_crm = champs & {"statut", "avancement", "motif", "nouveau", "supprime"}
    if champs == {"echeance"} or (champs <= {"echeance", "situation", "jours_restants", "jours_retard"} and "echeance" in champs):
        return ids, "modification de l'échéance"
    if donnees_crm:
        return ids, "crm: mise à jour"
    return ids, "temporel: échéance ou seuil atteint"


def synchroniser(projet_id: int) -> bool:
    """Garantit que la synthèse, les prévisions de risque et les recommandations du projet reposent sur l'état RÉEL du CRM.
    Si un écart existe (ex. échéance décalée), la phase rapide (calcul Python, instantanée) est relancée tout de suite, sans
    attendre l'IA ni un événement du CRM. Retourne True si une mise à jour a été faite."""
    with _lock:                                           # une seule resynchronisation à la fois (les pages interrogent toutes les 2 s)
        with SessionLocal() as db:
            projet = projects.get(db, projet_id)
            tickets, tracking, _ = snapshot(db, projet)
            derniere = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == projet_id)
                                  .order_by(SyntheseSuivi.id.desc()).limit(1)).first()
            if derniere is None or not tickets:
                return False                              # première évaluation : assurée par l'évaluation automatique
            ids, nature = ecarts(derniere.chiffres, tickets, tracking)
            if not nature:
                return False
        reevaluate(projet_id, ids, nature)
        return True


# ---------- A. Suivi événementiel : flux de changements du CRM ----------
def poll_crm_events():
    try:
        with SessionLocal() as db:
            cursor = settings_store.get(db, "crm_cursor", 0)
        try:
            if cursor > crm.dernier_evenement_id():   # CRM réinitialisé (jeu de test relancé) : on repart de zéro
                cursor = 0
        except Exception:
            pass
        events = crm.evenements(cursor)
        _retablir("crm_evenements", "CRM de nouveau joignable : le suivi des événements reprend.")
        if not events:
            return
        for e in events:                                   # projet supprimé dans le CRM : ses données ici aussi
            if e["type"] == "suppression_projet" and e.get("projet_id"):
                with SessionLocal() as db:
                    p = db.scalars(select(Projet).where(Projet.crm_projet_id == e["projet_id"])).first()
                    if p:
                        projects.purge(db, p)
        par_projet: dict[int, dict] = {}
        for e in events:
            # Événements du CRM (y compris les tickets créés par l'équipe). Les écritures du backend lui-même (échéance,
            # indicateur de retard, création par validation) restent ignorées pour éviter tout écho.
            if e["source"] == "crm" and e["ticket_id"] and e.get("projet_id"):
                g = par_projet.setdefault(e["projet_id"], {"ids": set(), "types": set()})
                g["ids"].add(e["ticket_id"])
                g["types"].add(e["type"])
        for crm_pid, g in par_projet.items():
            try:      # une erreur sur un projet ne doit pas empêcher le suivi des autres (ni bloquer le curseur)
                with SessionLocal() as db:
                    projet = projects.get_or_create_for_crm(db, crm_pid, f"Projet {crm_pid}")
                    pid = projet.id
                reevaluate(pid, g["ids"], "crm: " + ", ".join(sorted(g["types"])))
            except Exception as ex:
                log.error("Suivi du projet CRM %s impossible, repris au prochain contrôle temporel : %s", crm_pid, ex)
        with SessionLocal() as db:
            settings_store.put(db, "crm_cursor", max(e["id"] for e in events))
    except Exception as e:
        _avertir_limite("crm_evenements", "Lecture des événements CRM impossible (CRM indisponible ?) : %s — nouvelle tentative automatique", e)


# ---------- B. Suivi temporel : le passage du temps change la situation d'une tâche ----------
def temporal_check():
    """Pour chaque projet : compare la situation calculée à la dernière connue ; réévalue seulement s'il y a changement
    (échéance atteinte/dépassée, jours de retard, seuil « à surveiller »). Le LLM n'est pas appelé en permanence."""
    try:
        with SessionLocal() as db:
            liste = [(p.id, p.nom) for p in projects.sync(db)]
        for pid, _nom in liste:
            try:
                _controle_temporel_projet(pid)
            except Exception as e:                    # un projet en erreur ne doit jamais empêcher le suivi des autres
                _avertir_limite(f"temporel_{pid}", "Contrôle temporel du projet %s impossible : %s", pid, e)
        _retablir("crm_temporel", "CRM de nouveau joignable : le contrôle temporel reprend.")
    except Exception as e:
        _avertir_limite("crm_temporel", "Contrôle temporel impossible (CRM indisponible ?) : %s — nouvelle tentative automatique", e)


def _controle_temporel_projet(pid: int):
    """Un projet : compare la situation calculée (date du jour, échéance, jours ouvrés) à la dernière connue et réévalue le cas échéant.
    Règle (Python) : date actuelle > échéance ET statut ≠ fermé → en retard. Les tâches en attente ou en cours sont traitées pareil ;
    le suivi signale, il ne replanifie jamais (l'échéance ne change que par décision du haut responsable)."""
    with _lock, SessionLocal() as db:
        projet = projects.get(db, pid)
        tickets, tracking, _ = snapshot(db, projet)
        if not tickets:
            return
        _sync_indicateur(tickets, tracking)
        last = {s.id_ticket: s for s in db.scalars(
            select(SuiviRetard).where(SuiviRetard.id_projet == pid)
            .distinct(SuiviRetard.id_ticket).order_by(SuiviRetard.id_ticket, SuiviRetard.date_calcul.desc()))}
        ana = {a.id_ticket: (a.contenu or {}).get("repere") or {} for a in db.scalars(
            select(AnalyseTicket).where(AnalyseTicket.id_projet == pid)
            .distinct(AnalyseTicket.id_ticket).order_by(AnalyseTicket.id_ticket, AnalyseTicket.id.desc()))}
        changed = {i for i, tr in tracking.items()
                   if (i not in last and tr["situation"] != "ferme")
                   or (tr["situation"] != "ferme" and not ana.get(i))      # jamais analysé : on rattrape
                   or (i in last and (last[i].situation != tr["situation"]
                                      or last[i].jours_de_retard != tr["jours_retard"]))
                   or (tr["situation"] != "ferme" and i in ana and ana[i]
                       and (ana[i].get("jours_restants") != tr["jours_restants"]
                            or ana[i].get("statut") != tickets[i]["statut"]
                            or ana[i].get("avancement") != tr["avancement"]))}
    if changed:
        reevaluate(pid, changed, "temporel: échéance ou seuil atteint")


# ---------- C. Évaluation initiale automatique ----------
def auto_evaluate():
    """Évaluation 100 % automatique, en arrière-plan : tout projet qui a des tickets mais aucune synthèse est évalué
    sans intervention (premier affichage, base réinitialisée, projet repris du CRM). Aucun bouton, aucune action à faire."""
    try:
        with SessionLocal() as db:
            sans_synthese = [p.id for p in projects.sync(db)
                             if db.scalars(select(SyntheseSuivi.id).where(SyntheseSuivi.id_projet == p.id).limit(1)).first() is None]
        for pid in sans_synthese:
            with SessionLocal() as db:
                tickets, _, _ = snapshot(db, projects.get(db, pid))
            if tickets:
                reevaluate_all(pid, "automatique")
    except Exception as e:
        log.warning("Évaluation automatique reportée : %s", e)


def chat(projet_id: int, question: str, historique: list[dict]) -> dict:
    """Chat conseiller : faits du CRM + priorités, risques, recommandations ouvertes et charge de l'équipe, tous calculés par Python."""
    with SessionLocal() as db:
        projet = projects.get(db, projet_id)
        tickets, tracking, _ = snapshot(db, projet)
        nom = projet.nom
        syn = db.scalars(select(SyntheseSuivi).where(SyntheseSuivi.id_projet == projet_id).order_by(SyntheseSuivi.id.desc())).first()
        ch = (syn.chiffres or {}) if syn else {}
        recos = db.scalars(select(Recommandation).where(Recommandation.id_projet == projet_id, Recommandation.decision.is_(None),
                                                        Recommandation.obsolete.is_(False)).limit(10)).all()
        taches = {t.id_ticket_crm: t for t in db.scalars(select(Tache).where(Tache.id_ticket_crm.in_(list(tickets) or [0])))}
        coches: dict[int, set] = {}
        for v in db.scalars(select(ValidationCritere).where(ValidationCritere.id_ticket.in_(list(tickets) or [0]))):
            coches.setdefault(v.id_ticket, set()).add(v.critere)
        etats = {i: T.etat_criteres(t.get("criteres_acceptation"), taches[i].criteres_acceptation if i in taches else None, t["titre"],
                                    t.get("description") or "", taches[i].source_dans_document if i in taches else "", coches.get(i),
                                    t["statut"], t.get("avancement_declare")) for i, t in tickets.items()}
        ctx = {"etats": etats, "projet_info": {"date_limite": projet.date_limite},
               "priorites": [p for p in ch.get("priorites", []) if p["id"] in tickets],
               "risques": [r for r in ch.get("risques", []) if r["id"] in tickets],
               "evolutions": [e if isinstance(e, str) else e.get("txt", "") for e in (ch.get("evolutions") or [])][:6],
               "recos": [{"id_ticket": r.id_ticket, "texte": r.texte} for r in recos if r.id_ticket in tickets]}
    try:
        noms = {m["id"]: m["nom"] for m in crm.membres()}
    except Exception:
        noms = {}
    par: dict[int, dict] = {}
    for i, t in tickets.items():
        if t["statut"] == "ferme":
            continue
        for m in t.get("membre_ids") or []:
            x = par.setdefault(m, {"nom": noms.get(m, f"Membre {m}"), "n": 0, "late": 0})
            x["n"] += 1
            x["late"] += tracking[i]["situation"] == "en_retard"
    ctx["noms"] = noms
    ctx["charge"] = sorted(par.values(), key=lambda x: -x["n"])
    try:
        return agent.chat_answer(nom, question, tickets, tracking, crm.historique, historique, ctx)
    except llm.LLMError:
        return agent.chat_conseil(nom, question, tickets, tracking, ctx, hors_ligne=True)
