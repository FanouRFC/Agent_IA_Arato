"""Agent IA : le LLM choisit l'outil suivant et s'arrête quand ses vérifications sont satisfaites.
L'agent n'a AUCUN accès au CRM : il reçoit des données et des fonctions de lecture fournies par le backend."""
import json
import logging
from dataclasses import dataclass
from typing import Callable

from . import llm
from . import tools as T

log = logging.getLogger("agent")
MAX_ITER = 10


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable
    terminal: bool = False  # outil final : renvoie {"ok": True} quand le résultat est conforme

    def schema(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": self.parameters}}


def extract_json(text: str):
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def run_agent(system: str, user: str, tool_list: list[Tool], max_iter: int = MAX_ITER) -> dict:
    """Boucle de raisonnement. Retourne {"result": args de l'outil final | JSON | None, "text": str}."""
    registry = {t.name: t for t in tool_list}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max_iter):
        msg = llm.chat(messages, tools=[t.schema() for t in tool_list])
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         **({"tool_calls": calls} if calls else {})})
        if not calls:
            return {"result": extract_json(msg.get("content") or ""), "text": msg.get("content") or ""}
        for c in calls:
            name = c["function"]["name"]
            tool = registry.get(name)
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
                out = tool.fn(**args) if tool else {"erreur": f"Outil inconnu : {name}"}
            except Exception as e:  # erreur renvoyée à l'agent pour auto-correction
                args, out = {}, {"erreur": str(e)}
            messages.append({"role": "tool", "tool_call_id": c.get("id", name),
                             "content": json.dumps(out, ensure_ascii=False, default=str)})
            if tool and tool.terminal and isinstance(out, dict) and out.get("ok"):
                return {"result": args, "text": ""}
    return {"result": None, "text": ""}


# =====================================================================================
# A. Création des tâches
# =====================================================================================
TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "numéro de la tâche : 1, 2, 3…"},
        "titre": {"type": "string"},
        "description": {"type": "string"},
        "criteres_acceptation": {"type": "array", "items": {"type": "string"}},
        "priorite": {"type": "string", "enum": ["haute", "moyenne", "basse"]},
        "raison_priorite": {"type": "string"},
        "duree_estimee_jours": {"type": "integer", "description": "jours ouvrés, ≥ 1"},
        "depend_de": {"type": "array", "items": {"type": "integer"}, "description": "ids des tâches préalables"},
        "source_dans_document": {"type": "string", "description": "extrait copié à l'identique du document"},
        "niveau_confiance": {"type": "number", "description": "0 à 1"},
        "profil_recommande": {"type": "string"},
        "membre_ids_proposes": {"type": "array", "items": {"type": "integer"}},
        "ambiguites": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "titre", "description", "priorite", "duree_estimee_jours", "source_dans_document"],
}
TASKS_PARAM = {"type": "object", "properties": {"taches": {"type": "array", "items": TASK_SCHEMA}},
               "required": ["taches"]}

SYSTEM_CREATION = """Tu es l'agent IA d'Arato. Tu analyses un cahier des charges et proposes des tâches. Réponds en français.
Démarche (tu choisis l'outil suivant selon ce que tu obtiens) :
1. Lis le document. 2. Si utile, appelle rechercher_informations (tickets existants, membres, profils).
3. Décompose en tâches, chacune avec une durée propre en JOURS OUVRÉS (pas de délai uniforme).
4. Appelle verifier_dependances. 5. Appelle verifier_coherence ; en cas de problème, reviens à la décomposition et corrige.
6. Termine par produire_taches (jamais d'autre sortie finale).
Règles : n'invente aucune tâche absente du document ; source_dans_document = extrait EXACT ; signale ambiguïtés et informations
manquantes ; propose des membres uniquement parmi ceux retournés par l'outil. Tu n'as aucun accès au CRM : tu produis un brouillon
que le haut responsable validera."""


def create_tasks(texte: str, ctx: dict) -> dict | None:
    doc = texte[:30000]

    def produire(taches: list[dict], ambiguites_globales: list[str] | None = None):
        errs = []
        dep = T.check_dependencies(taches)
        if not dep["ok"]:
            errs.append(f"Dépendances invalides : {dep}")
        errs += [p for p in T.check_coherence(taches, doc)["problemes"] if "source_dans_document" not in p]
        return {"ok": not errs, "erreurs": errs}

    tool_list = [
        Tool("rechercher_informations", "Cherche tickets, membres et profils du système.",
             {"type": "object", "properties": {"requete": {"type": "string"}}, "required": ["requete"]},
             lambda requete: T.search_info(ctx, requete)),
        Tool("verifier_dependances", "Détecte cycles et références invalides ; renvoie l'ordre d'exécution.",
             TASKS_PARAM, lambda taches: T.check_dependencies(taches)),
        Tool("verifier_coherence", "Doublons, manques, contradictions, fidélité au document.",
             TASKS_PARAM, lambda taches: T.check_coherence(taches, doc)),
        Tool("produire_taches", "Remet les tâches structurées au backend (sortie finale).",
             {"type": "object", "properties": {"taches": TASKS_PARAM["properties"]["taches"],
                                               "ambiguites_globales": {"type": "array", "items": {"type": "string"}}},
              "required": ["taches"]}, produire, terminal=True),
    ]
    res = run_agent(SYSTEM_CREATION, f"Cahier des charges :\n\n{doc}", tool_list, max_iter=14)["result"]
    if not res or not res.get("taches"):
        return None
    membres_ok = {m["id"] for m in ctx["membres"]}
    normalisees = []
    for t in res["taches"]:
        warn = []
        src_ok = T._norm(t.get("source_dans_document", "")) in T._norm(doc)
        conf = float(t.get("niveau_confiance") or 0.5)
        if not src_ok:
            conf, warn = conf * 0.5, ["Source non retrouvée à l'identique dans le document : à vérifier"]
        normalisees.append({**t, "niveau_confiance": max(0.0, min(1.0, conf)),
                            "ambiguites": list(t.get("ambiguites") or []) + warn,
                            "membre_ids_proposes": [i for i in (t.get("membre_ids_proposes") or []) if i in membres_ok]})
    return {"taches": normalisees, "ambiguites_globales": res.get("ambiguites_globales") or []}


# =====================================================================================
# B. Suivi dynamique : analyse d'un ticket
# =====================================================================================
SYSTEM_SUIVI = """Tu es l'agent IA de suivi d'Arato. Tu t'adresses UNIQUEMENT au haut responsable ; tu n'as aucun pouvoir d'action.
Règles strictes :
- Tu t'appuies uniquement sur les chiffres fournis par les outils Python (retard, jours de retard, échéance, avancement). Tu ne calcules
  jamais de date ni de jours.
- L'avancement est DÉCLARÉ par le membre : écris « l'avancement déclaré est de X % » ; n'écris jamais qu'une tâche « ne progresse pas ».
- N'invente jamais une cause. Sans motif documenté, constate-le : « aucune cause de retard n'est actuellement documentée ».
- Un ticket « en attente » en retard : le motif d'attente explique la situation, aucun second motif n'est demandé.
- Vocabulaire neutre : vérifier, examiner, contacter la personne concernée, anticiper, demander au membre de préciser la cause.
  Le mot « relance » est INTERDIT.
- Choisis UN diagnostic prioritaire : historique (blocage ponctuel ou répétitif ?), impact_systemique (la tâche bloque-t-elle d'autres
  tâches ?), manque_de_visibilite (absence de motif alors que la situation l'exigerait ?).
- Recommandation : 1 à 3 phrases courtes, format « T-014 : [constat chiffré]. [analyse issue de l'historique, des dépendances ou du
  manque de motif]. [action recommandée]. » Ne répète pas ce que le tableau de bord affiche déjà.
Démarche : enquête (lire_historique_ticket, lire_tickets_lies si besoin), analyse, puis soumettre_analyse (sortie finale)."""


def _allowed_numbers(t, tr, hf, related) -> set[int]:
    nums = {t["id"], tr["avancement"], tr["jours_retard"], hf["nb_blocages"], len(hf["motifs_attente"]),
            len(related["depend_de"]), len(related["bloque"])}
    nums |= {x for x in (tr["jours_restants"], tr["retard_final"]) if x is not None}
    nums |= {a["de"] for a in hf["avancements"]} | {a["a"] for a in hf["avancements"]}
    for r in related["depend_de"] + related["bloque"]:
        nums |= {r["id"], r["jours_retard"]}
    return nums


def _fallback_analysis(t, tr, hf, fb):
    risque = "eleve" if tr["situation"] == "en_retard" and tr["avancement"] <= 50 else \
        "modere" if tr["situation"] in ("en_retard", "a_surveiller") else "faible"
    analyse = f"{tr['libelle']}. L'avancement déclaré est de {tr['avancement']} %."
    if hf["nb_blocages"]:
        analyse += f" Le ticket a connu {hf['nb_blocages']} période(s) d'attente."
    return {"analyse": analyse, "risque": risque, "prediction": "", "diagnostic": fb[1] if fb else "",
            "recommandation": fb[0] if fb else None, "source": "fallback"}


def analyse_ticket(t: dict, tr: dict, hist: dict, related: dict, get_history: Callable[[int], dict]) -> dict:
    hf = T.history_facts(hist)
    motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
    allowed = _allowed_numbers(t, tr, hf, related)
    fb = T.recommendation_fallback(t, tr, motif)

    def soumettre(analyse, risque, prediction, diagnostic, recommandation=None):
        errs = []
        if risque not in ("faible", "modere", "eleve"):
            errs.append("risque : faible, modere ou eleve")
        if diagnostic not in ("historique", "impact_systemique", "manque_de_visibilite", ""):
            errs.append("diagnostic invalide")
        if T.numbers_in(analyse + " " + prediction) - allowed:
            errs.append("Chiffres absents des résultats Python dans l'analyse ou la prédiction")
        if recommandation:
            errs += T.check_recommendation(recommandation, t["id"], allowed)
        elif fb:
            errs.append("Une recommandation est requise pour cette situation")
        return {"ok": not errs, "erreurs": errs}

    tool_list = [
        Tool("lire_historique_ticket", "Statuts, avancements déclarés, motifs d'attente et de retard successifs.",
             {"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]},
             lambda ticket_id: T.history_facts(get_history(ticket_id))),
        Tool("lire_tickets_lies", "Dépendances du ticket et tickets qu'il bloque (avec leur situation calculée).",
             {"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]},
             lambda ticket_id: related),
        Tool("soumettre_analyse", "Sortie finale : analyse, risque, prédiction, diagnostic, recommandation.",
             {"type": "object", "properties": {
                 "analyse": {"type": "string"}, "risque": {"type": "string", "enum": ["faible", "modere", "eleve"]},
                 "prediction": {"type": "string"},
                 "diagnostic": {"type": "string", "enum": ["historique", "impact_systemique", "manque_de_visibilite"]},
                 "recommandation": {"type": "string"}},
              "required": ["analyse", "risque", "prediction", "diagnostic"]}, soumettre, terminal=True),
    ]
    user = json.dumps({"ticket": {"id": t["id"], "titre": t["titre"], "statut": t["statut"],
                                  "motif_attente": t.get("motif_attente_courant"),
                                  "motif_retard": t.get("motif_retard_courant")},
                       "calculs_python": tr, "historique": hf, "tickets_lies": related},
                      ensure_ascii=False, default=str)
    try:
        res = run_agent(SYSTEM_SUIVI, user, tool_list, max_iter=8)["result"]
        if res and soumettre(**{k: res.get(k, "") for k in ("analyse", "risque", "prediction", "diagnostic")},
                             recommandation=res.get("recommandation"))["ok"]:
            return {**{k: res.get(k) for k in ("analyse", "risque", "prediction", "diagnostic", "recommandation")},
                    "source": "llm"}
    except Exception as e:
        log.warning("Analyse LLM indisponible pour T-%s : %s", t["id"], e)
    return _fallback_analysis(t, tr, hf, fb)


# =====================================================================================
# Synthèse dynamique et chat
# =====================================================================================
def synthese_deterministe(f: dict) -> str:
    n = len(f["en_retard"])
    parts = [f"{n} tâche{'s' if n > 1 else ''} {'sont' if n > 1 else 'est'} actuellement en retard." if n
             else "Aucune tâche n'est actuellement en retard."]
    for r in f["en_retard"][:6]:
        motif = f"motif : {r['motif']}" if r["motif"] else "aucun motif documenté"
        parts.append(f"T-{r['id']:03d} : {r['jours_retard']} jour(s) de retard, avancement déclaré {r['avancement']} %, {motif}.")
    for r in f["a_surveiller"][:6]:
        parts.append(f"T-{r['id']:03d} : à surveiller, échéance dans {r['jours_restants']} jour(s) ouvré(s), "
                     f"avancement déclaré {r['avancement']} %.")
    if f["evolutions"]:
        parts.append("Depuis la dernière analyse : " + " ".join(f["evolutions"]))
    return " ".join(parts)


def synthese_narrative(f: dict) -> str:
    """Synthèse rédigée par le LLM ; rejetée si un chiffre diffère de Python ou si « relance » apparaît."""
    system = ("Tu rédiges la synthèse dynamique de la situation du projet pour le haut responsable, en français, en 5 phrases "
              "maximum, à partir des seuls faits fournis. N'écris aucun chiffre absent des faits, n'invente aucune cause, "
              "n'utilise jamais le mot « relance ». Termine par une recommandation du type « vérifier en priorité T-014 ».")
    try:
        txt = llm.chat([{"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(f, ensure_ascii=False)}])["content"].strip()
        if txt and not (T.numbers_in(txt) - T.numbers_in(json.dumps(f))) and "relanc" not in txt.lower():
            return txt
    except Exception as e:
        log.warning("Synthèse LLM indisponible : %s", e)
    return synthese_deterministe(f)


SYSTEM_CHAT = """Tu réponds au haut responsable d'Arato, en français, uniquement à partir des données réelles fournies par les outils
(lister_tickets, lire_ticket, lire_historique_ticket). Ne calcule aucune date ni aucun retard : cite les chiffres des outils.
N'invente aucune cause ; si aucun motif n'est documenté, dis-le. Tu n'agis sur rien. N'utilise jamais le mot « relance »."""


def chat_answer(question: str, tickets: dict[int, dict], tracking: dict[int, dict], get_history: Callable) -> str:
    def lister(situation: str = ""):
        return [{"id": i, "titre": tickets[i]["titre"], **{k: tr[k] for k in ("statut", "situation", "libelle", "avancement")}}
                for i, tr in tracking.items() if not situation or tr["situation"] == situation]

    sit = {"type": "object", "properties": {"situation": {"type": "string",
           "enum": ["", "en_retard", "a_surveiller", "normale", "ferme"]}}}
    tid = {"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]}
    tool_list = [
        Tool("lister_tickets", "Liste des tickets avec situation calculée par Python.", sit, lister),
        Tool("lire_ticket", "Détail d'un ticket et calculs Python.", tid,
             lambda ticket_id: {**tickets[ticket_id], "calculs_python": tracking[ticket_id]}),
        Tool("lire_historique_ticket", "Historique des statuts, avancements et motifs.", tid,
             lambda ticket_id: T.history_facts(get_history(ticket_id))),
    ]
    try:
        r = run_agent(SYSTEM_CHAT, question, tool_list, max_iter=6)
        return r["text"] or (json.dumps(r["result"], ensure_ascii=False) if r["result"] else "Je n'ai pas pu répondre.")
    except Exception as e:
        log.warning("Chat indisponible : %s", e)
        return "Le modèle d'IA est momentanément indisponible. Le tableau de bord reste à jour."
