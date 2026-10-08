"""Outils Python DÉTERMINISTES. Le LLM les appelle et interprète leurs résultats ; il ne calcule jamais."""
import datetime as dt
import difflib
import re
from pathlib import Path

from .calendar_utils import bd_between


# ---------- Extraction du document ----------
def clean_text(t: str) -> str:
    t = t.replace("\x00", "")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def extract_text(path: str) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    elif ext == ".docx":
        import docx
        d = docx.Document(path)
        text = "\n".join(par.text for par in d.paragraphs)
        for tb in d.tables:
            for row in tb.rows:
                text += "\n" + " | ".join(c.text for c in row.cells)
    else:
        text = p.read_text(encoding="utf-8", errors="ignore")
    return clean_text(text)


# ---------- Dépendances et cohérence ----------
def check_dependencies(taches: list[dict]) -> dict:
    """Cycles, références inconnues, ordre d'exécution (tri topologique)."""
    ids = {t["id"] for t in taches}
    deps = {t["id"]: list(t.get("depend_de") or []) for t in taches}
    unknown = [(i, d) for i, ds in deps.items() for d in ds if d not in ids or d == i]
    indeg = {i: len([d for d in ds if d in ids and d != i]) for i, ds in deps.items()}
    ordre, queue = [], sorted(i for i, n in indeg.items() if n == 0)
    while queue:
        n = queue.pop(0)
        ordre.append(n)
        for i, ds in deps.items():
            if n in ds and i != n:
                indeg[i] -= 1
                if indeg[i] == 0:
                    queue.append(i)
    cycle = sorted(set(ids) - set(ordre))
    return {"ok": not unknown and not cycle, "references_invalides": unknown, "taches_en_cycle": cycle,
            "ordre": ordre if not cycle else []}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def check_coherence(taches: list[dict], texte_document: str) -> dict:
    """Doublons, manques, contradictions, fidélité au document."""
    problemes, doc = [], _norm(texte_document)
    for i, a in enumerate(taches):
        for b in taches[i + 1:]:
            if difflib.SequenceMatcher(None, _norm(a["titre"]), _norm(b["titre"])).ratio() > 0.88:
                problemes.append(f"Doublon probable : tâches {a['id']} et {b['id']}")
    for t in taches:
        n = t["id"]
        if not (t.get("description") or "").strip():
            problemes.append(f"Tâche {n} : description manquante")
        if not isinstance(t.get("duree_estimee_jours"), int) or t["duree_estimee_jours"] < 1:
            problemes.append(f"Tâche {n} : durée estimée invalide (entier ≥ 1 jour ouvré)")
        elif t["duree_estimee_jours"] > 60:
            problemes.append(f"Tâche {n} : durée de {t['duree_estimee_jours']} jours, à découper")
        if t.get("priorite") not in ("haute", "moyenne", "basse"):
            problemes.append(f"Tâche {n} : priorité invalide (haute, moyenne ou basse)")
        src = _norm(t.get("source_dans_document", ""))
        if not src or src not in doc:
            problemes.append(f"Tâche {n} : source_dans_document absente ou non copiée à l'identique du document")
    return {"ok": not problemes, "problemes": problemes}


def search_info(ctx: dict, requete: str) -> dict:
    """Recherche limitée aux données autorisées fournies par le backend (aucun service externe)."""
    mots = [m for m in re.findall(r"\w{3,}", requete.lower())]

    def score(txt):
        txt = (txt or "").lower()
        return sum(m in txt for m in mots)

    tickets = sorted(ctx.get("tickets", []), key=lambda t: -score(t["titre"] + " " + (t.get("description") or "")))
    membres = sorted(ctx.get("membres", []), key=lambda m: -score(m["nom"] + " " + m["profil"]))
    return {
        "tickets": [{"id": t["id"], "titre": t["titre"], "statut": t["statut"]} for t in tickets[:5]
                    if score(t["titre"] + " " + (t.get("description") or "")) > 0],
        "membres": [{"id": m["id"], "nom": m["nom"], "profil": m["profil"]} for m in membres[:8]],
        "profils": ctx.get("profils", []),
    }


# ---------- Calcul du suivi (retards, jours de retard, échéances proches) ----------
def _j(n: int) -> str:
    return f"{n} jour{'s' if n > 1 else ''} ouvré{'s' if n > 1 else ''}"


def compute_tracking(t: dict, now: dt.datetime, holidays, seuil_jours=2, seuil_av=50,
                     work_end: dt.time = dt.time(17, 0)) -> dict:
    """Règle : date actuelle > échéance ET statut ≠ fermé → en retard. Retourne tous les chiffres de référence."""
    ech = dt.date.fromisoformat(str(t["echeance"]))
    today = now.date()
    r = {"id": t["id"], "statut": t["statut"], "avancement": t["avancement_declare"], "echeance": ech.isoformat(),
         "est_en_retard": False, "jours_retard": 0, "jours_restants": None, "retard_final": None}
    if t["statut"] == "ferme":
        fin = dt.date.fromisoformat(str(t["date_fermeture"])) if t.get("date_fermeture") else today
        n = bd_between(ech, fin, holidays) if fin > ech else 0
        r.update(retard_final=n, situation="ferme",
                 libelle=f"Fermé (retard final : {_j(n)})" if n else "Fermé dans les délais")
        return r
    if today > ech or (today == ech and now.time() >= work_end):
        n = bd_between(ech, today, holidays)
        if t["statut"] == "en_attente":
            lib = f"En attente, échéance dépassée de {_j(n)}" if n else "En attente, échéance dépassée"
        else:
            lib = f"En retard de {_j(n)}" if n else "Échéance dépassée aujourd'hui"
        r.update(est_en_retard=True, jours_retard=n, situation="en_retard", libelle=lib)
        return r
    restants = bd_between(today, ech, holidays)
    r["jours_restants"] = restants
    if restants <= seuil_jours and t["avancement_declare"] <= seuil_av:
        quand = "aujourd'hui" if restants == 0 else "demain" if restants == 1 else f"dans {_j(restants)}"
        r.update(situation="a_surveiller", libelle=f"À surveiller (échéance {quand})")
    else:
        r.update(situation="normale", libelle=f"Échéance dans {_j(restants)}")
    return r


def history_facts(hist: dict) -> dict:
    """Faits chiffrés tirés de l'historique CRM (nombre de blocages, motifs successifs)."""
    attentes = [h for h in hist["statuts"] if h["type_motif"] == "attente"]
    retards = [h for h in hist["statuts"] if h["type_motif"] == "retard"]
    return {
        "nb_blocages": len(attentes),
        "motifs_attente": [{"motif": h["motif"], "date": str(h["date"])[:10],
                            "resolu": bool(h["date_resolution"])} for h in attentes],
        "motifs_retard": [{"motif": h["motif"], "date": str(h["date"])[:10]} for h in retards],
        "avancements": [{"de": a["ancienne"], "a": a["nouvelle"], "date": str(a["date"])[:10]}
                        for a in hist["avancements"]],
    }


# ---------- Contrôles de conformité des textes de l'agent ----------
NUM = re.compile(r"\d+")


def numbers_in(text: str) -> set[int]:
    return {int(x) for x in NUM.findall(text)}


def check_recommendation(text: str, ticket_id: int, allowed: set[int]) -> list[str]:
    """Format imposé, vocabulaire, fidélité aux chiffres de Python."""
    errs, low = [], text.lower()
    if not text.startswith(f"T-{ticket_id:03d} :"):
        errs.append(f"Doit commencer par « T-{ticket_id:03d} : »")
    if len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]) > 3:
        errs.append("Trop long : constat chiffré, analyse, action (courtes phrases)")
    if "relanc" in low:
        errs.append("Le terme « relance » est interdit")
    if "ne progresse pas" in low:
        errs.append("Écrire « l'avancement déclaré est de X % », jamais « ne progresse pas »")
    inconnus = numbers_in(text) - allowed
    if inconnus:
        errs.append(f"Chiffres absents des résultats Python : {sorted(inconnus)}")
    return errs


def recommendation_fallback(t: dict, tr: dict, motif: str | None) -> tuple[str, str] | None:
    """Recommandation déterministe (si le LLM est indisponible ou non conforme)."""
    tid = f"T-{t['id']:03d}"
    if tr["situation"] == "en_retard":
        n = tr["jours_retard"]
        constat = f"En retard de {_j(n)}" if n else "Échéance dépassée aujourd'hui"
        if not motif:
            return (f"{tid} : {constat} sans motif documenté. Ce manque d'information limite le pilotage. "
                    "Il est recommandé de demander au membre de préciser la cause.", "manque_de_visibilite")
        return (f"{tid} : {constat}, motif documenté « {motif} ». "
                "Il est recommandé d'examiner la situation avec le membre concerné.", "historique")
    if tr["situation"] == "a_surveiller":
        return (f"{tid} : À surveiller (échéance dans {_j(tr['jours_restants'])}, avancement déclaré "
                f"{tr['avancement']} %). Il est recommandé de vérifier les éventuels blocages et de surveiller la tâche.",
                "historique")
    if t["statut"] == "en_attente":
        return (f"{tid} : En attente, motif documenté « {motif or 'non précisé'} ». "
                "Il est recommandé de vérifier l'état du blocage.", "historique")
    return None
