"""Chat de suivi.

Le LLM traduit la question en filtres ; Python filtre, compte et trie sur les données réelles du CRM ;
le LLM rédige ensuite la réponse. Si sa réponse cite un ticket ou un chiffre absent des résultats,
elle est remplacée par une réponse déterministe construite à partir des mêmes résultats.
"""
import datetime as dt
import json
import logging
import re
import unicodedata
from collections import Counter

from . import tools as T
from .agent import Tool, run_agent

log = logging.getLogger("chat")

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
STATUTS = ["nouveau", "ouvert", "en_cours", "en_attente", "ferme"]
SITUATIONS = ["en_retard", "a_surveiller", "normale", "ferme"]
MAX_LIGNES = 25  # taille maximale d'un résultat envoyé au modèle (contexte limité)


# ---------- Utilitaires ----------
def _ref(i: int) -> str:
    return f"T-{i:03d}"


def _n(s) -> str:
    """Minuscules sans accents."""
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _id(v) -> int | None:
    m = re.search(r"\d+", str(v if v is not None else ""))
    return int(m.group()) if m else None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _date(v) -> dt.date | None:
    if v in (None, ""):
        return None
    s = _n(v)
    today = dt.date.today()
    if s in ("aujourd'hui", "aujourdhui", "today"):
        return today
    if s in ("demain", "tomorrow"):
        return today + dt.timedelta(days=1)
    if s in ("hier", "yesterday"):
        return today - dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _fr(d) -> str:
    try:
        return dt.date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return "—"


# ---------- Données : une ligne complète par ticket ----------
def _rows(tickets: dict, tracking: dict, membres: list, projets: list) -> list[dict]:
    mb = {m["id"]: m["nom"] for m in membres}
    pj = {p["id"]: p["nom"] for p in projets}
    rows = []
    for i, t in tickets.items():
        tr = tracking.get(i)
        if not tr:
            continue
        motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
        noms = [mb.get(m, f"membre {m}") for m in t.get("membre_ids", [])]
        projet = pj.get(t.get("projet_id"), "")
        rows.append({
            "id": i, "ref": _ref(i), "titre": t["titre"], "projet": projet,
            "statut": t["statut"], "situation": tr["situation"], "etat": tr["libelle"],
            "avancement_declare": tr["avancement"], "echeance": tr["echeance"],
            "jours_ouvres_restants": tr["jours_restants"], "jours_retard": tr["jours_retard"],
            "date_creation": str(t.get("date_creation") or "")[:10],
            "membres": noms, "motif": motif,
            "depend_de": [_ref(d) for d in t.get("depend_de_ids", [])],
            "_desc": t.get("description") or "",
            "_txt": _n(" ".join([t["titre"], t.get("description") or "", projet, motif or ""])),
        })
    return rows


def _exposer(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _filtrer(rows: list[dict], f: dict) -> list[dict]:
    cree_a, cree_b = _date(f.get("cree_apres")), _date(f.get("cree_avant"))
    ech_a, ech_b = _date(f.get("echeance_apres")), _date(f.get("echeance_avant"))
    jr, jrm = _int(f.get("jours_restants")), _int(f.get("jours_restants_max"))
    projet, membre = _n(f.get("projet")), _n(f.get("membre"))
    mots = _n(f.get("texte")).split()
    out = []
    for r in rows:
        if f.get("statut") and r["statut"] != f["statut"]:
            continue
        if f.get("situation") and r["situation"] != f["situation"]:
            continue
        if projet and projet not in _n(r["projet"]):
            continue
        if membre and not any(membre in _n(m) for m in r["membres"]):
            continue
        if mots and not all(m in r["_txt"] for m in mots):
            continue
        if cree_a and r["date_creation"] < cree_a.isoformat():
            continue
        if cree_b and (not r["date_creation"] or r["date_creation"] > cree_b.isoformat()):
            continue
        if ech_a and r["echeance"] < ech_a.isoformat():
            continue
        if ech_b and r["echeance"] > ech_b.isoformat():
            continue
        rest = r["jours_ouvres_restants"]
        if jr is not None and rest != jr:
            continue
        if jrm is not None and (rest is None or rest > jrm):
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r["echeance"], r["id"]))


# ---------- Filet de sécurité : intention déduite de la question (si le modèle n'appelle aucun outil) ----------
def _intention(question: str) -> dict | None:
    x, f = _n(question), {}
    if re.search(r"\bretard", x):
        f["situation"] = "en_retard"
    elif "surveill" in x:
        f["situation"] = "a_surveiller"
    if "en attente" in x:
        f["statut"] = "en_attente"
    if re.search(r"\bcre\w*\s+aujourd", x):
        f["cree_apres"] = f["cree_avant"] = "aujourd'hui"
    elif re.search(r"\bcre\w*\s+hier", x):
        f["cree_apres"] = f["cree_avant"] = "hier"
    if m := re.search(r"(\d+)\s+prochains?\s+jours?", x):
        f["jours_restants_max"] = int(m.group(1))
    elif m := re.search(r"dans\s+(\d+)\s+jours?", x):
        f["jours_restants"] = int(m.group(1))
    return f or None


# ---------- Réponse déterministe et contrôle de cohérence ----------
def _texte_deterministe(p: dict) -> str:
    n = p["nombre"]
    if not n:
        crit = ", ".join(f"{k} = {v}" for k, v in p["filtres_appliques"].items()) or "aucun filtre"
        return f"Aucun ticket ne correspond à ces critères ({crit})."
    tete = f"{n} ticket{'s' if n > 1 else ''} correspond{'ent' if n > 1 else ''} :"
    if p.get("note"):
        tete += f" ({p['note']})"
    lignes = [f"{t['ref']} : {t['titre']} — {t['etat']}, échéance {_fr(t['echeance'])}" for t in p["tickets"]]
    return tete + "\n" + "\n".join(lignes)


def _incoherent(texte: str, vus: set[int], question: str, sorties: list[str]) -> bool:
    """Vrai si la réponse cite un ticket ou un chiffre absent des résultats des outils."""
    cites = {int(x) for x in re.findall(r"T-0*(\d+)", texte)}
    if cites - vus - {int(x) for x in re.findall(r"T-0*(\d+)", question)}:
        return True
    permis = T.numbers_in(" ".join(sorties) + " " + question + " " + dt.date.today().isoformat())
    sans_numerotation = re.sub(r"(?m)^\s*\d+[.)]\s+", "", texte)
    return bool(T.numbers_in(sans_numerotation) - permis)


# ---------- Prompt ----------
def _system() -> str:
    d = dt.date.today()
    return f"""Tu es l'assistant de suivi d'Arato. Tu réponds au haut responsable, en français, uniquement à partir des résultats des outils.
Date du jour : {JOURS[d.weekday()]} {d.strftime('%d/%m/%Y')} (ISO {d.isoformat()}). Les « jours » sont des jours ouvrés, comme dans le tableau de bord.
Règles :
- Appelle TOUJOURS un outil avant de répondre à une question sur les tickets. Ne réponds jamais de mémoire.
- Liste ou comptage : rechercher_tickets. Ticket précis : lire_ticket (et lire_historique_ticket pour son historique). Totaux : statistiques.
- Traduction des questions en filtres :
  « créés aujourd'hui » -> cree_apres="aujourd'hui" et cree_avant="aujourd'hui" ;
  « en retard » -> situation="en_retard" ; « à surveiller » -> situation="a_surveiller" ; « en attente » -> statut="en_attente" ;
  « échéant dans 2 jours » -> jours_restants=2 ; « dans les 3 prochains jours » -> jours_restants_max=3 ;
  « de Karim » -> membre="Karim" ; « du projet X » -> projet="X".
- Réponse : indique le champ « nombre », puis une ligne par ticket « T-014 : titre — état, échéance jj/mm/aaaa ». N'ajoute aucun ticket absent du résultat.
- Si « nombre » vaut 0, dis qu'aucun ticket ne correspond et rappelle les filtres appliqués. Si « note » est présent, précise que la liste est partielle.
- Ne calcule aucune date ni aucun retard. N'invente aucune cause : sans motif documenté, dis-le. N'utilise jamais le mot « relance ». Tu n'agis sur rien."""


def _compose(question: str, historique: list | None) -> str:
    h = [m for m in (historique or []) if isinstance(m, dict) and m.get("text")][-6:]
    if not h:
        return question
    lignes = "\n".join(f"{'Responsable' if m.get('role') == 'moi' else 'Assistant'} : {str(m['text'])[:400]}" for m in h)
    return (f"Contexte de la conversation (peut être périmé : interroge à nouveau les outils) :\n{lignes}\n\n"
            f"Question : {question}")


# ---------- Point d'entrée ----------
def answer(question: str, tickets: dict, tracking: dict, membres: list, projets: list, get_history,
           historique: list | None = None) -> dict:
    rows = _rows(tickets, tracking, membres, projets)
    par_id = {r["id"]: r for r in rows}
    vus: set[int] = set()
    sorties: list[str] = []
    recherches: list[dict] = []
    appels: list[str] = []
    fiche: list[dict] = []  # ticket lu individuellement

    def rechercher(**f):
        norm: dict = {}
        for cle, valides in (("statut", STATUTS), ("situation", SITUATIONS)):
            if f.get(cle) not in (None, ""):
                v = _n(f[cle]).replace(" ", "_")
                if v not in valides:
                    return {"erreur": f"{cle} inconnu. Valeurs possibles : {valides}"}
                norm[cle] = v
        for cle in ("cree_apres", "cree_avant", "echeance_apres", "echeance_avant"):
            if f.get(cle) not in (None, ""):
                d = _date(f[cle])
                if d is None:
                    return {"erreur": f"{cle} : date invalide (AAAA-MM-JJ, « aujourd'hui », « hier » ou « demain »)"}
                norm[cle] = d.isoformat()
        for cle in ("jours_restants", "jours_restants_max"):
            if f.get(cle) not in (None, ""):
                if _int(f[cle]) is None:
                    return {"erreur": f"{cle} doit être un entier"}
                norm[cle] = _int(f[cle])
        for cle in ("projet", "membre", "texte"):
            if f.get(cle) not in (None, ""):
                norm[cle] = str(f[cle])
        res = _filtrer(rows, norm)
        out = [_exposer(r) for r in res[:MAX_LIGNES]]
        vus.update(r["id"] for r in res[:MAX_LIGNES])
        p = {"date_du_jour": dt.date.today().isoformat(), "filtres_appliques": norm, "nombre": len(res), "tickets": out}
        if len(res) > MAX_LIGNES:
            p["note"] = f"{MAX_LIGNES} premiers sur {len(res)}"
        recherches.append(p)
        return p

    def lire_ticket(ticket_id=None, **_):
        i = _id(ticket_id)
        r = par_id.get(i) if i is not None else None
        if not r:
            return {"erreur": f"Ticket {ticket_id} introuvable"}
        bloque = [_ref(j) for j, o in tickets.items() if i in o.get("depend_de_ids", [])]
        vus.add(i)
        vus.update(_id(d) for d in r["depend_de"])
        vus.update(_id(b) for b in bloque)
        fiche[:] = [_exposer(r)]
        return {**_exposer(r), "description": r["_desc"], "bloque": bloque}

    def historique_ticket(ticket_id=None, **_):
        i = _id(ticket_id)
        if i is None or i not in par_id:
            return {"erreur": f"Ticket {ticket_id} introuvable"}
        vus.add(i)
        return T.history_facts(get_history(i))

    def statistiques(**_):
        return {"total": len(rows), "par_statut": dict(Counter(r["statut"] for r in rows)),
                "par_situation": dict(Counter(r["situation"] for r in rows)),
                "par_projet": dict(Counter(r["projet"] or "sans projet" for r in rows))}

    def enreg(nom, fn):
        def run(**kw):
            appels.append(nom)
            out = fn(**kw)
            sorties.append(json.dumps(out, ensure_ascii=False, default=str))
            return out
        return run

    s = lambda d: {"type": "string", "description": d}
    outil_recherche = enreg("rechercher_tickets", rechercher)
    tid_schema = {"type": "object", "properties": {"ticket_id": {"type": "integer", "description": "Numéro du ticket (14 pour T-014)"}},
                  "required": ["ticket_id"]}
    outils = [
        Tool("rechercher_tickets", "Liste filtrée de tickets (filtrage et comptage faits par Python). Tous les filtres sont optionnels et se combinent.",
             {"type": "object", "properties": {
                 "statut": {"type": "string", "enum": STATUTS, "description": "Statut CRM"},
                 "situation": {"type": "string", "enum": SITUATIONS, "description": "État de l'échéance calculé par Python"},
                 "projet": s("Nom, ou partie du nom, du projet"),
                 "membre": s("Nom, ou partie du nom, d'un membre affecté"),
                 "texte": s("Mots à chercher dans le titre, la description ou le motif"),
                 "cree_apres": s("Créé à partir de cette date : AAAA-MM-JJ, « aujourd'hui », « hier » ou « demain »"),
                 "cree_avant": s("Créé au plus tard à cette date (même format)"),
                 "echeance_apres": s("Échéance à partir de cette date (même format)"),
                 "echeance_avant": s("Échéance au plus tard à cette date (même format)"),
                 "jours_restants": {"type": "integer", "description": "Échéance dans EXACTEMENT N jours ouvrés (« dans 2 jours »)"},
                 "jours_restants_max": {"type": "integer", "description": "Échéance dans au plus N jours ouvrés (« dans les 2 prochains jours »)"},
             }}, outil_recherche),
        Tool("lire_ticket", "Détail complet d'un ticket : description, membres, motif, dépendances, tickets bloqués.",
             tid_schema, enreg("lire_ticket", lire_ticket)),
        Tool("lire_historique_ticket", "Historique d'un ticket : statuts, avancements, motifs d'attente et de retard.",
             tid_schema, enreg("lire_historique_ticket", historique_ticket)),
        Tool("statistiques", "Totaux par statut, par état d'échéance et par projet.",
             {"type": "object", "properties": {}}, enreg("statistiques", statistiques)),
    ]

    system, user, texte = _system(), _compose(question, historique), ""
    try:
        for essai in range(2):
            consigne = user if essai == 0 else user + "\n\nRappel : appelle d'abord un outil, puis réponds."
            texte = (run_agent(system, consigne, outils, max_iter=6)["text"] or "").strip()
            if appels:
                break
    except Exception as e:
        log.warning("Chat : modèle indisponible : %s", e)
        texte = ""

    if not appels:  # le modèle n'a rien consulté : on déduit les filtres de la question
        f = _intention(question)
        if f:
            outil_recherche(**f)
        texte = ""

    if recherches:
        if not texte or _incoherent(texte, vus, question, sorties):
            texte = _texte_deterministe(recherches[-1])
    elif not texte:
        texte = ("Je n'ai pas pu consulter les données pour répondre. "
                 "Reformulez la question, ou utilisez le tableau de bord.")

    dernier = recherches[-1] if recherches else None
    return {"reponse": texte, "tickets": dernier["tickets"] if dernier else fiche,
            "total": dernier["nombre"] if dernier else len(fiche),
            "filtres": dernier["filtres_appliques"] if dernier else {}}
