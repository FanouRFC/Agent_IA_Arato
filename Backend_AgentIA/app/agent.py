"""Agent IA : le LLM choisit l'outil suivant et s'arrête quand ses vérifications sont satisfaites.
L'agent n'a AUCUN accès au CRM : il reçoit des données et des fonctions de lecture fournies par le backend."""
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable

from . import llm
from .config import settings
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


def run_agent(system: str, user: str, tool_list: list[Tool], max_iter: int = MAX_ITER,
              history: list[dict] | None = None, max_tokens: int | None = None) -> dict:
    """Boucle de raisonnement. Retourne {"result": args de l'outil final | JSON | None, "text": str,
    "trace": sorties des outils (pour vérifier la fidélité aux chiffres)}."""
    registry = {t.name: t for t in tool_list}
    messages = [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": user}]
    trace: list[str] = []
    schemas = [t.schema() for t in tool_list]
    for _ in range(max_iter):
        msg = llm.chat(messages, tools=schemas, max_tokens=max_tokens)
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": (msg.get("content") or None) if calls else (msg.get("content") or ""),
                         **({"tool_calls": calls} if calls else {})})
        if not calls:
            return {"result": extract_json(msg.get("content") or ""), "text": msg.get("content") or "", "trace": trace}
        for c in calls:
            name = c["function"]["name"]
            tool = registry.get(name)
            try:
                raw = c["function"].get("arguments") or "{}"
                args = raw if isinstance(raw, dict) else json.loads(raw)
                out = tool.fn(**args) if tool else {"erreur": f"Outil inconnu : {name}"}
            except Exception as e:  # erreur renvoyée à l'agent pour auto-correction
                args, out = {}, {"erreur": str(e)}
            dumped = json.dumps(out, ensure_ascii=False, default=str)
            trace.append(dumped)
            messages.append({"role": "tool", "tool_call_id": c.get("id") or name, "name": name, "content": dumped})
            if tool and tool.terminal and isinstance(out, dict) and out.get("ok"):
                return {"result": args, "text": "", "trace": trace}
    return {"result": None, "text": "", "trace": trace}


# =====================================================================================
# A. Création des tâches
# =====================================================================================
TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "numéro de la tâche : 1, 2, 3…"},
        "titre": {"type": "string"},
        "description": {"type": "string"},
        "priorite": {"type": "string", "enum": ["haute", "moyenne", "basse"]},
        "raison_priorite": {"type": "string"},
        "duree_estimee_jours": {"type": "integer", "description": "nombre de jours, ≥ 1"},
        "depend_de": {"type": "array", "items": {"type": "integer"}, "description": "ids des tâches préalables"},
        "source_dans_document": {"type": "string", "description": "extrait copié à l'identique du document"},
        "niveau_confiance": {"type": "number", "description": "0 à 1"},
        "profil_recommande": {"type": "string"},
        "nb_membres_recommande": {"type": "integer", "description": "1 (tâche simple), 2 ou 3 (tâche longue ou pluridisciplinaire)"},
        "membre_ids_proposes": {"type": "array", "items": {"type": "integer"}},
        "ambiguites": {"type": "array", "items": {"type": "string"}},
        "criteres_acceptation": {"type": "array", "items": {"type": "string"},
                                 "description": "conditions vérifiables, tirées du document ; liste vide si le document est insuffisant"},
    },
    "required": ["id", "titre", "description", "priorite", "duree_estimee_jours", "source_dans_document"],
}
TASKS_PARAM = {"type": "object", "properties": {"taches": {"type": "array", "items": TASK_SCHEMA}},
               "required": ["taches"]}

SYSTEM_CREATION = """Tu es l'agent IA d'Arato. Tu analyses un cahier des charges et proposes des tâches. Réponds en français.
Démarche (tu choisis l'outil suivant selon ce que tu obtiens) :
1. Lis le document. 2. Si utile, appelle rechercher_informations (tickets existants, membres, profils).
3. Décompose en tâches, chacune avec une durée propre en JOURS (pas de délai uniforme).
4. Appelle verifier_dependances. 5. Appelle verifier_coherence ; en cas de problème, reviens à la décomposition et corrige.
6. Termine par produire_taches (jamais d'autre sortie finale).
Règles : n'invente aucune tâche absente du document ; UNE exigence = UNE tâche : ne propose jamais deux tâches qui couvrent la même exigence ni de tâches répétitives (étudier, documenter, tester… recopiés pour chaque exigence) : regroupe-les ; source_dans_document = extrait EXACT ; signale ambiguïtés et informations
manquantes ; propose des membres uniquement parmi ceux retournés par l'outil ; renseigne nb_membres_recommande (1 pour une tâche simple, 2 ou 3 pour une tâche longue ou pluridisciplinaire) : une même tâche peut être confiée à plusieurs personnes. Tu n'as aucun accès au CRM : tu produis un brouillon
que le haut responsable validera."""


SYSTEM_JSON = """Tu es l'agent IA d'Arato. Extrais du cahier des charges les tâches à réaliser. Réponds en français par UN SEUL objet JSON,
sans texte autour :
{"taches":[{"id":1,"titre":"","description":"","priorite":"haute|moyenne|basse","raison_priorite":"",
"duree_estimee_jours":3,"depend_de":[],"source_dans_document":"extrait EXACT","niveau_confiance":0.8,"profil_recommande":"",
"nb_membres_recommande":1,"membre_ids_proposes":[],"ambiguites":[]}],"ambiguites_globales":[]}
Consignes : durées en jours (entiers ≥ 1), propres à chaque tâche ; description en une phrase ; raison_priorite en cinq mots maximum ; source_dans_document = une phrase courte copiée à l'identique ; nb_membres_recommande :
1 (tâche simple), 2 ou 3 (tâche longue ou pluridisciplinaire) ; membre_ids_proposes : uniquement des ids de la liste des membres
fournie ; depend_de : ids des tâches préalables de cette demande, sans cycle ; ambiguites : seulement les plus importantes.
N'invente aucune tâche absente du document. UNE exigence = UNE tâche : jamais deux tâches pour la même exigence, jamais de tâches
répétitives recopiées pour chaque exigence (regroupe-les en une seule, avec une durée adaptée)."""


def _txt(v) -> str:
    """Texte sûr : le modèle renvoie parfois des objets ({"titre": …}) au lieu de chaînes."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for k in ("texte", "text", "titre", "title", "description", "nom", "libelle", "contenu", "value"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k].strip()
        return " — ".join(_txt(x) for x in v.values() if x not in (None, "", [], {}))
    if isinstance(v, (list, tuple)):
        return " ; ".join(x for x in (_txt(i) for i in v) if x)
    return str(v)


def _liste(v) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, (list, tuple)):
        v = [v]
    return [x for x in (_txt(i) for i in v) if x]


def _entiers(v) -> list[int]:
    """Liste d'identifiants entiers, même si le modèle renvoie des objets ({"id": 1}) ou des chaînes."""
    out = []
    for d in (v if isinstance(v, (list, tuple)) else [v] if v not in (None, "") else []):
        try:
            out.append(int(d["id"] if isinstance(d, dict) else d))
        except (TypeError, ValueError, KeyError):
            pass
    return out


def _assainir(res: dict | None) -> dict | None:
    """Rend la sortie brute du modèle exploitable (types, identifiants uniques) avant toute vérification."""
    if not res or not isinstance(res.get("taches"), list):
        return res
    res["taches"] = [t for t in res["taches"] if isinstance(t, dict)]
    vus: set[int] = set()
    for k, t in enumerate(res["taches"], 1):
        ids = _entiers(t.get("id"))
        t["id"] = ids[0] if ids and ids[0] not in vus else max(vus | {0}) + 1
        vus.add(t["id"])
        t["depend_de"] = _entiers(t.get("depend_de"))
    return res


def _decouper(doc: str, taille: int) -> list[str]:
    """Coupe le document en blocs d'environ `taille` caractères, aux fins de ligne."""
    blocs, cur = [], ""
    for ligne in doc.splitlines(keepends=True):
        while len(ligne) > taille:                       # ligne géante : on la coupe
            if cur:
                blocs.append(cur)
                cur = ""
            blocs.append(ligne[:taille])
            ligne = ligne[taille:]
        if cur and len(cur) + len(ligne) > taille:
            blocs.append(cur)
            cur = ""
        cur += ligne
    if cur.strip():
        blocs.append(cur)
    return [b for b in blocs if b.strip()]


def _extraction_directe(doc: str, ctx: dict, partie: tuple[int, int] | None = None) -> dict | None:
    """Un seul appel au modèle ; les vérifications sont faites par Python. `partie` = (numéro, total) d'un bloc."""
    membres = "\n".join(f"- id {m['id']} : {m['nom']} ({m['profil']})" for m in ctx["membres"]) or "(aucun)"
    entete = (f"Ceci est la partie {partie[0]}/{partie[1]} du cahier des charges. "
              "N'extrais QUE les tâches de cette partie (6 au maximum), numérotées à partir de 1.\n\n") if partie else ""
    msg = llm.chat([{"role": "system", "content": SYSTEM_JSON},
                    {"role": "user", "content": f"Membres disponibles :\n{membres}\n\n{entete}Cahier des charges :\n{doc}"}],
                   temperature=0.1, max_tokens=2000 if partie else 2500, json_mode=True)
    res = _assainir(extract_json(msg.get("content") or ""))
    if res and res.get("taches") and not T.check_dependencies(res["taches"])["ok"]:
        for t in res["taches"]:
            t["depend_de"] = []
        res.setdefault("ambiguites_globales", []).append(
            "Dépendances proposées incohérentes : à reconstituer à la relecture.")
    return res


def _extraction_par_blocs(doc: str, ctx: dict) -> dict | None:
    """Mode par défaut : un appel par bloc de texte, tâches fusionnées et renumérotées, budget de temps global."""
    taille = int(getattr(settings, "llm_chunk_chars", 3000))
    budget = int(getattr(settings, "llm_budget_secondes", 600))      # durée maximale de l'analyse complète
    blocs = _decouper(doc, taille)
    if len(blocs) <= 1:
        return _extraction_directe(doc, ctx)

    debut = time.monotonic()
    taches: list[dict] = []
    globales: list[str] = []
    vus: set[str] = set()
    echecs: list[int] = []
    for i, bloc in enumerate(blocs, 1):
        if time.monotonic() - debut > budget:
            globales.append(f"Analyse interrompue après {budget // 60} min : les parties {i} à {len(blocs)} du document "
                            "n'ont pas été analysées.")
            break
        try:
            res = _extraction_directe(bloc, ctx, (i, len(blocs)))
        except llm.LLMError:
            if i == 1 and not taches:
                raise                                    # fournisseur indisponible dès le départ : erreur claire
            echecs.append(i)
            continue
        except Exception as e:                           # sortie malformée du modèle pour ce bloc
            log.warning("Bloc %s/%s non analysé : %s", i, len(blocs), e)
            echecs.append(i)
            continue
        if not res or not res.get("taches"):
            continue
        globales += res.get("ambiguites_globales") or []
        ajoutees, remap = [], {}
        for k, t in enumerate(res["taches"], 1):
            cle = T._norm(t.get("titre", ""))
            if not cle or cle in vus:                    # doublon d'un bloc précédent
                continue
            vus.add(cle)
            remap[t.get("id") or k] = len(taches) + 1
            t["id"] = len(taches) + 1
            taches.append(t)
            ajoutees.append(t)
        for t in ajoutees:                               # dépendances : ids locaux au bloc → ids globaux
            t["depend_de"] = [remap[d] for d in (t.get("depend_de") or []) if d in remap]

    if not taches:
        return None
    if not T.check_dependencies(taches)["ok"]:
        for t in taches:
            t["depend_de"] = []
        globales.append("Dépendances proposées incohérentes : à reconstituer à la relecture.")
    globales.append(f"Document analysé en {len(blocs)} parties : les dépendances entre parties sont à vérifier à la relecture.")
    if echecs:
        globales.append("Parties non analysées (modèle indisponible ou réponse illisible) : " + ", ".join(map(str, echecs)) + ".")
    return {"taches": taches, "ambiguites_globales": list(dict.fromkeys(globales))}


def _boucle_agentique(doc: str, ctx: dict) -> dict | None:
    """Mode complet (lent) : boucle d'outils avec vérifications par le modèle."""
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
    return run_agent(SYSTEM_CREATION, f"Cahier des charges :\n\n{doc}", tool_list, max_iter=14, max_tokens=6000)["result"]



# =====================================================================================
# A ter. Critères d'acceptation (rédigés par l'IA à partir du document, contrôlés par Python)
# =====================================================================================
SYSTEM_CRITERES = """Tu es l'agent IA d'Arato. Pour chaque tâche fournie, rédige ses critères d'acceptation : des conditions précises,
compréhensibles et VÉRIFIABLES (on peut répondre par oui ou par non) qui permettront au haut responsable de décider que la tâche est
réellement terminée.
Règles strictes :
- Appuie-toi UNIQUEMENT sur l'extrait du cahier des charges fourni pour la tâche (champs « extrait » et « contexte ») : reprends les
  comportements, formats, valeurs, délais et contraintes qui y figurent.
- N'invente aucune exigence, aucun chiffre, aucune technologie absents de l'extrait.
- TOUJOURS de 2 à 4 critères par tâche, chacun en UNE phrase courte, claire et actionnable (« L'utilisateur peut … », « Le système affiche … »).
- Interdit : formules génériques (« le travail est terminé », « fonctionne correctement », « conforme aux attentes », « de qualité »).
- Si l'extrait est peu détaillé, rédige quand même des critères vérifiables à partir du titre et de la description de la tâche
  (résultat observable, livrable présenté, comportement constatable) SANS ajouter de chiffre, de délai ni de technologie qui n'y figurent pas.
  Ne renvoie jamais une liste vide.
Réponds par UN SEUL objet JSON, sans texte autour : {"criteres":[{"id":1,"criteres_acceptation":["…","…"]}]}"""

_CRITERES_PAR_APPEL = 4


def _contexte_source(doc: str, source: str, rayon: int = 450) -> str:
    """Passage du cahier des charges autour de la source citée par la tâche (vide si elle n'est pas retrouvée)."""
    mots = (source or "").split()
    if not mots:
        return ""
    m = re.search(r"\s+".join(re.escape(w) for w in mots[:14]), doc, re.IGNORECASE)
    if not m:
        return ""
    return doc[max(0, m.start() - rayon): m.end() + rayon].strip()


def generer_criteres(taches: list[dict], doc: str) -> dict:
    """Rédige les critères d'acceptation de chaque tâche (une requête pour 4 tâches) puis les contrôle avec Python : formule creuse,
    absence de lien avec le document ou valeur inventée → critère écarté. Sans information suffisante, la tâche n'a AUCUN critère et
    des critères PAR DÉFAUT (déduits de l'énoncé de la tâche, sans fait inventé) sont proposés et l'ambiguïté signalée au relecteur : une tâche a
    toujours des critères. Retourne {"avec": n (critères du modèle), "sans": n (critères par défaut), "erreur": str|None}."""
    for t in taches:                                     # critères éventuellement fournis par le mode agentique : contrôlés aussi
        t["criteres_acceptation"] = t.get("criteres_acceptation") or []
    contextes = {t["id"]: _contexte_source(doc, t.get("source_dans_document", "")) for t in taches}
    erreur = None
    for i in range(0, len(taches), _CRITERES_PAR_APPEL):
        lot = taches[i:i + _CRITERES_PAR_APPEL]
        payload = [{"id": t["id"], "titre": t["titre"], "description": (t.get("description") or "")[:300],
                    "extrait": (t.get("source_dans_document") or "")[:400], "contexte": contextes[t["id"]][:1000]} for t in lot]
        propose: dict[int, list] = {t["id"]: _liste(t.get("criteres_acceptation")) for t in lot}
        try:
            msg = llm.chat([{"role": "system", "content": SYSTEM_CRITERES},
                            {"role": "user", "content": json.dumps({"taches": payload}, ensure_ascii=False)}],
                           temperature=0.1, max_tokens=1500, json_mode=True)
            res = extract_json(msg.get("content") or "") or {}
            for d in res.get("criteres") or []:
                if isinstance(d, dict):
                    for tid in _entiers(d.get("id")):
                        if tid in propose:
                            propose[tid] += _liste(d.get("criteres_acceptation"))
        except llm.LLMError as e:
            erreur = str(e)
        except Exception as e:                           # sortie malformée : les tâches du lot restent sans critère
            log.warning("Critères d'acceptation : réponse inexploitable (%s)", e)
            erreur = erreur or "réponse du modèle inexploitable"
        for t in lot:
            contexte = " ".join([t["titre"], t.get("description") or "", t.get("source_dans_document") or "", contextes[t["id"]]])
            retenus, rejets = T.validate_criteria(propose[t["id"]], contexte)
            if rejets:
                log.info("Critères écartés pour la tâche %s : %s", t["id"], " | ".join(rejets))
            t["criteres_acceptation"] = retenus
    sans = [t for t in taches if not t["criteres_acceptation"]]
    for t in sans:             # jamais de tâche sans critère : critères par défaut tirés de l'énoncé de la tâche, signalés au relecteur
        t["criteres_acceptation"] = T.criteres_par_defaut(t["titre"], t.get("description") or "", t.get("source_dans_document") or "")
        t["ambiguites"] = list(t.get("ambiguites") or []) + [
            "Critères d'acceptation proposés par défaut à partir de l'énoncé de la tâche (document peu détaillé) : à affiner à la relecture."]
    return {"avec": len(taches) - len(sans), "sans": len(sans), "erreur": erreur}


# =====================================================================================
# A bis. Dépendances logiques entre tâches (établies par l'IA, validées par Python)
# =====================================================================================
SYSTEM_DEPS = """Tu es l'agent IA d'Arato. On te donne la liste numérotée des tâches d'UN projet. Établis les dépendances logiques :
une tâche dépend d'une autre quand elle ne peut pas commencer avant que l'autre soit terminée (concevoir avant développer,
développer avant tester, tester avant déployer…). N'ajoute une dépendance que si elle est évidente ; deux tâches indépendantes
n'ont aucune dépendance ; jamais de cycle ; jamais de dépendance d'une tâche envers elle-même ; utilise uniquement les numéros fournis.
Réponds par UN SEUL objet JSON, sans texte autour : {"dependances":[{"id":3,"depend_de":[1,2]}]}"""

# Repli déterministe : ordre naturel d'un projet (cadrer → concevoir → réaliser → tester → livrer)
PHASES = (
    ("analyse", "cadrage", "recueil", "specification", "etude", "audit", "diagnostic"),
    ("conception", "maquette", "architecture", "modelis", "design", "wireframe", "prototype", "planification"),
    ("developp", "implement", "integration", "realisation", "codage", "creation", "configuration", "installation", "mise en place"),
    ("test", "recette", "validation", "verification", "controle qualite", "qualite"),
    ("deploiement", "deployer", "mise en production", "livraison", "migration", "formation", "lancement", "go live"),
)


def _phase(titre: str) -> int | None:
    n = T._norm(unicodedata.normalize("NFD", titre or "")).encode("ascii", "ignore").decode()
    for rang in range(len(PHASES) - 1, -1, -1):          # le mot le plus « avancé » l'emporte (ex. « tests de déploiement »)
        if any(k in n for k in PHASES[rang]):
            return rang
    return None


def _ajouter_sans_cycle(taches: list[dict], aretes: list[tuple[int, int]]) -> int:
    """Ajoute des dépendances (tâche, préalable) en refusant toute arête qui créerait un cycle. Retourne le nombre ajouté."""
    par_id = {t["id"]: t for t in taches}
    n = 0
    for tid, pre in aretes:
        if tid == pre or tid not in par_id or pre not in par_id or pre in par_id[tid]["depend_de"]:
            continue
        par_id[tid]["depend_de"] = sorted({*par_id[tid]["depend_de"], pre})
        if T.check_dependencies(taches)["ok"]:
            n += 1
        else:
            par_id[tid]["depend_de"] = [d for d in par_id[tid]["depend_de"] if d != pre]
    return n


def _dependances_par_phases(taches: list[dict]) -> list[tuple[int, int]]:
    rang = {t["id"]: _phase(t["titre"]) for t in taches}
    aretes = []
    for t in taches:
        r = rang[t["id"]]
        if r is None:
            continue
        avant = [o["id"] for o in taches if rang[o["id"]] is not None and rang[o["id"]] < r]
        if avant:
            proche = max(rang[i] for i in avant)         # la phase immédiatement précédente
            aretes += [(t["id"], i) for i in avant if rang[i] == proche][:3]
    return aretes


def cartographier_dependances(taches: list[dict]) -> int:
    """Établit les dépendances logiques entre les tâches : l'IA propose, Python valide (références connues, aucun cycle).
    Si l'IA est indisponible ou ne trouve rien, l'ordre naturel d'un projet sert de repli. Retourne le nombre d'arêtes ajoutées."""
    if len(taches) < 2:
        return 0
    ajoutees = 0
    try:
        liste = [{"id": t["id"], "titre": t["titre"], "description": (t.get("description") or "")[:160]} for t in taches[:60]]
        msg = llm.chat([{"role": "system", "content": SYSTEM_DEPS},
                        {"role": "user", "content": json.dumps({"taches": liste}, ensure_ascii=False)}],
                       temperature=0.1, max_tokens=1500, json_mode=True)
        res = extract_json(msg.get("content") or "") or {}
        aretes = []
        for d in res.get("dependances") or []:
            if isinstance(d, dict):
                for tid in _entiers(d.get("id")):
                    aretes += [(tid, pre) for pre in _entiers(d.get("depend_de"))]
        ajoutees += _ajouter_sans_cycle(taches, aretes)
    except Exception as e:                                # l'IA indisponible ne doit jamais bloquer la création des tâches
        log.warning("Cartographie des dépendances par l'IA indisponible : %s", e)
    if not any(t["depend_de"] for t in taches):
        ajoutees += _ajouter_sans_cycle(taches, _dependances_par_phases(taches))
    return ajoutees


def create_tasks(texte: str, ctx: dict) -> dict | None:
    limite = settings.llm_max_doc_chars
    doc = texte[:limite]
    tronque = len(texte) > limite

    agentique = bool(getattr(settings, "creation_agentique", False))      # False = mode rapide (par défaut)
    modes = [_boucle_agentique, _extraction_par_blocs] if agentique else [_extraction_par_blocs]
    res = None
    for i, mode in enumerate(modes):
        try:
            res = mode(doc, ctx)
        except llm.LLMError:
            raise
        except Exception as e:  # sortie malformée du modèle : on tente l'autre mode
            log.warning("Création des tâches (%s) interrompue : %s", mode.__name__, e)
        if res and res.get("taches"):
            break
    if not res or not res.get("taches"):
        return None

    membres_ok = {m["id"] for m in ctx["membres"]}
    normalisees = []
    for k, t in enumerate(res["taches"], 1):
        warn = []
        src_ok = T._norm(_txt(t.get("source_dans_document"))) in T._norm(doc)
        try:
            conf = float(t.get("niveau_confiance") or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        if not src_ok:
            conf, warn = conf * 0.5, ["Source non retrouvée à l'identique dans le document : à vérifier"]
        try:
            duree = max(1, int(t.get("duree_estimee_jours") or 1))
        except (TypeError, ValueError):
            duree = 1
        prio = t.get("priorite") if t.get("priorite") in ("haute", "moyenne", "basse") else "moyenne"
        try:
            nb = int(t.get("nb_membres_recommande"))
            nb = nb if 1 <= nb <= 3 else None            # valeur absurde : la règle de secours prendra le relais
        except (TypeError, ValueError):
            nb = None
        try:
            tid_ = int(t.get("id") or k)
        except (TypeError, ValueError):
            tid_ = k
        deps = []
        for d in (t.get("depend_de") or []):
            try:
                deps.append(int(d["id"] if isinstance(d, dict) else d))
            except (TypeError, ValueError, KeyError):
                pass
        normalisees.append({**t, "id": tid_, "duree_estimee_jours": duree, "priorite": prio,
                            "titre": _txt(t.get("titre")) or f"Tâche {k}", "description": _txt(t.get("description")),
                            "raison_priorite": _txt(t.get("raison_priorite")), "depend_de": deps,
                            "source_dans_document": _txt(t.get("source_dans_document")),
                            "profil_recommande": _txt(t.get("profil_recommande")),
                            "nb_membres_recommande": nb,
                            "niveau_confiance": max(0.0, min(1.0, conf)),
                            "ambiguites": _liste(t.get("ambiguites")) + warn,
                            "criteres_acceptation": T.clean_criteria(_liste(t.get("criteres_acceptation"))),
                            "membre_ids_proposes": [i for i in (t.get("membre_ids_proposes") or []) if i in membres_ok]})
    # Tâches répétitives (même exigence reformulée) : fusionnées avant la numérotation, dépendances redirigées
    normalisees, fusionnees = T.dedoublonner_taches(normalisees)
    # Numérotation 1..n garantie unique (le modèle peut répéter ou sauter des identifiants) ; dépendances réécrites
    remap: dict[int, int] = {}
    for n, t in enumerate(normalisees, 1):
        remap.setdefault(t["id"], n)
    for n, t in enumerate(normalisees, 1):
        t["depend_de"] = sorted({remap[d] for d in t["depend_de"] if d in remap and remap[d] != n})
        t["id"] = n
    if not T.check_dependencies(normalisees)["ok"]:
        for t in normalisees:
            t["depend_de"] = []
    nb_deps = cartographier_dependances(normalisees)         # dépendances logiques entre tâches (IA + contrôle Python)
    bilan_criteres = generer_criteres(normalisees, doc)       # critères d'acceptation (IA à partir du document + contrôle Python)
    globales = _liste(res.get("ambiguites_globales"))
    if fusionnees:
        globales.append(f"{len(fusionnees)} tâche(s) répétitive(s) fusionnée(s) avec une tâche existante : " + " ; ".join(f"« {x} »" for x in fusionnees[:5]) + ".")
    if bilan_criteres["erreur"]:
        globales.append("Modèle indisponible pour les critères d'acceptation (" + bilan_criteres["erreur"] + ") : critères par défaut proposés, à affiner à la relecture.")
    elif bilan_criteres["sans"]:
        globales.append(f"{bilan_criteres['sans']} tâche(s) avec des critères d'acceptation par défaut (document peu détaillé) : à affiner à la relecture.")
    if nb_deps:
        globales.append(f"{nb_deps} dépendance(s) entre tâches établie(s) par l'agent : à vérifier à la relecture.")
    if tronque:
        globales.append(f"Document tronqué à {limite} caractères pour l'analyse ({len(texte)} reçus) : "
                        "les tâches de la fin du document peuvent manquer.")
    return {"taches": normalisees, "ambiguites_globales": globales}


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
- Avancement et statut sont indépendants : un ticket à 100 % d'avancement déclaré n'est PAS fermé. Sa clôture attend la décision du
  haut responsable : recommande d'examiner le ticket et de valider sa clôture si le travail est terminé ; n'écris jamais qu'il est
  « terminé » ou « fermé » tant que son statut n'est pas « Fermé ».
- Choisis UN diagnostic prioritaire : historique (blocage ponctuel ou répétitif ?), impact_systemique (la tâche bloque-t-elle d'autres
  tâches ?), manque_de_visibilite (absence de motif alors que la situation l'exigerait ?).
- Recommandation : 1 à 3 phrases courtes, format « T-014 : [constat chiffré]. [analyse issue de l'historique, des dépendances ou du
  manque de motif]. [action recommandée]. » Ne répète pas ce que le tableau de bord affiche déjà.
Style : chaque recommandation doit être propre au ticket (avancement déclaré, tâches bloquées en aval, motif, mises en attente
  répétées, proximité de l'échéance). Évite les formules génériques (« vérifier les éventuels blocages et surveiller la tâche ») et ne
  répète jamais la même action d'un ticket à l'autre : donne l'action qui a du sens POUR CE ticket (renfort, report, arbitrage, date ferme…).
Démarche : enquête (lire_historique_ticket, lire_tickets_lies si besoin), analyse, puis soumettre_analyse (sortie finale)."""


def _allowed_numbers(t, tr, hf, related) -> set[int]:
    nums = {t["id"], tr["avancement"], tr["jours_retard"], hf["nb_blocages"], len(hf["motifs_attente"]),
            len(related["depend_de"]), len(related["bloque"])}
    nums |= {x for x in (tr["jours_restants"], tr["retard_final"]) if x is not None}
    nums |= {a["de"] for a in hf["avancements"]} | {a["a"] for a in hf["avancements"]}
    for r in related["depend_de"] + related["bloque"]:
        nums |= {r["id"], r["jours_retard"]}
    return nums


STATUT_LIB = {"nouveau": "Nouveau", "ouvert": "Ouvert", "en_cours": "En cours", "en_attente": "En attente", "ferme": "Fermé"}


def _fallback_analysis(t, tr, hf, fb):
    """Analyse calculée par Python seul (modèle indisponible ou ticket sans enjeu) : reflète l'état et l'historique réels."""
    risque = "eleve" if tr["situation"] == "en_retard" and tr["avancement"] <= 50 else \
        "modere" if tr["situation"] in ("en_retard", "a_surveiller") else "faible"
    analyse = f"{STATUT_LIB.get(t['statut'], t['statut'])} · {tr['libelle']}. L'avancement déclaré est de {tr['avancement']} %."
    if hf["nb_blocages"]:
        analyse += f" Le ticket a connu {hf['nb_blocages']} période(s) d'attente."
    if hf["avancements"]:
        d = hf["avancements"][-1]
        analyse += f" Dernière mise à jour de l'avancement : de {d['de']} % à {d['a']} %."
    if tr["situation"] == "en_retard":
        prediction = "Sans changement, le retard va se prolonger."
    elif tr["situation"] == "a_surveiller":
        prediction = "Au rythme actuel, l'échéance risque de ne pas être tenue."
    else:
        prediction = ""
    return {"analyse": analyse, "risque": risque, "prediction": prediction, "diagnostic": fb[1] if fb else "",
            "recommandation": fb[0] if fb else None, "source": "fallback"}


def analyse_simple(t: dict, tr: dict, hist: dict, related: dict | None = None) -> dict:
    """Analyse sans appel au modèle (ticket sans enjeu ou fermé) : toujours à jour avec l'état réel."""
    hf = T.history_facts(hist)
    fb = T.recommendation_fallback(t, tr, t.get("motif_retard_courant") or t.get("motif_attente_courant"),
                                   {"nb_blocages": hf["nb_blocages"], "bloque": len((related or {}).get("bloque") or [])})
    return _fallback_analysis(t, tr, hf, fb)


def analyse_ticket(t: dict, tr: dict, hist: dict, related: dict, get_history: Callable[[int], dict]) -> dict:
    hf = T.history_facts(hist)
    motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
    allowed = _allowed_numbers(t, tr, hf, related)
    fb = T.recommendation_fallback(t, tr, motif, {"nb_blocages": hf["nb_blocages"], "bloque": len(related.get("bloque") or [])})

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
# Synthèse dynamique et chat (toujours dans le contexte d'UN SEUL projet)
# =====================================================================================
def _tids(ids) -> str:
    return ", ".join(f"T-{i:03d}" for i in ids)


def _pl(n: int, un: str, plusieurs: str) -> str:
    return un if n == 1 else plusieurs


def _raison_courte(p: dict) -> str:
    """Première raison d'une priorité, sans le détail d'avancement (« échéance dans 1 jour »)."""
    r = (p.get("raisons") or [""])[0]
    return r.split(", avancement")[0].strip()


def synthese_deterministe(f: dict) -> str:
    """Synthèse courte et lisible : 1) l'état réel du projet (chaque tâche comptée une seule fois : en retard, à surveiller,
    en attente, terminée), 2) ce qui vient de changer, 3) la recommandation. Le détail (priorités, risques, évolution) se
    trouve dans les rubriques de la page, il n'est pas répété ici."""
    nr, ns, na = len(f["en_retard"]), len(f["a_surveiller"]), len(f["en_attente"])
    nt, total = len(f.get("termine") or []), f.get("total") or 0
    parts = []
    if total and nt == total:
        parts.append(f"Projet « {f['projet']} » : toutes les tâches ({total}) sont terminées.")
    elif not (nr or ns or na):
        parts.append(f"Aucune tâche du projet « {f['projet']} » ne nécessite d'attention particulière"
                     + (f" ({nt} {_pl(nt, 'terminée', 'terminées')})." if nt else "."))
    else:
        elems = []
        if nr:
            elems.append(f"{nr} {_pl(nr, 'tâche', 'tâches')} en retard")
        if ns:
            elems.append(f"{ns} {_pl(ns, 'tâche', 'tâches')} à surveiller" if not elems else f"{ns} à surveiller")
        if na:
            elems.append(f"{na} en attente" if elems else f"{na} {_pl(na, 'tâche', 'tâches')} en attente")
        if nt:
            elems.append(f"{nt} {_pl(nt, 'terminée', 'terminées')}")
        parts.append(f"Projet « {f['projet']} » : " + ", ".join(elems) + ".")
    if f["evolutions"]:
        # Les ajouts de tâches sont TOUJOURS cités en entier (aucune ne peut être omise) ; le reste est résumé.
        ajouts = [e for e in f["evolutions"] if "ajoutée" in e]
        autres = [e for e in f["evolutions"] if "ajoutée" not in e]
        morceaux = []
        if ajouts:
            ids = sorted({int(x) for e in ajouts for x in re.findall(r"T-0*(\d+)", e)})
            liste = _tids(ids) if len(ids) == 1 else _tids(ids[:-1]) + " et " + _tids(ids[-1:])
            morceaux.append(("La tâche " if len(ids) == 1 else "Les tâches ") + liste + _pl(len(ids), " a été ajoutée", " ont été ajoutées"))
        if len(autres) == 1:
            morceaux.append(autres[0].rstrip("."))
        elif autres:
            morceaux.append(f"{len(autres)} {'autres ' if ajouts else ''}évolutions (voir « Évolution »)")
        parts.append("Depuis la dernière analyse : " + " ; ".join(morceaux) + ".")
    prio = f["priorites"][:2]
    if prio:
        reco = f"vérifier en priorité {_tids([prio[0]['id']])}"
        if _raison_courte(prio[0]):
            reco += f" ({_raison_courte(prio[0])})"
        if len(prio) > 1:
            reco += f", puis {_tids([prio[1]['id']])}"
        parts.append(f"Recommandation : {reco}.")
    return " ".join(parts)


def synthese_narrative(f: dict) -> tuple[str, str]:
    """Synthèse rédigée par le LLM ; rejetée si un chiffre ou un ticket diffère des faits Python, si elle est trop longue
    ou si « relance » apparaît. Retourne (texte, source)."""
    system = ("Tu rédiges la synthèse de la situation d'UN projet pour le haut responsable, en français, en TROIS phrases courtes "
              "au maximum (60 mots au total), à partir des seuls faits fournis. 1) L'état du projet : nombre de tâches en retard, "
              "à surveiller, en attente et terminées (chaque tâche n'est comptée qu'une fois ; n'écris rien sur une catégorie vide). "
              "2) Seulement s'il y en a, le changement le plus important depuis la dernière analyse. "
              "3) Une recommandation du type « vérifier en priorité T-014 » (la première priorité fournie). "
              "N'écris aucun chiffre ni identifiant de ticket absent des faits, n'invente aucune cause, n'écris jamais « relance ». "
              "Ne détaille pas les risques ni chaque tâche : ils figurent ailleurs. "
              "Si des tâches ont été ajoutées au projet, cite-les TOUTES (aucune ne doit manquer).")
    try:
        txt = (llm.chat([{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(f, ensure_ascii=False)}])["content"] or "").strip()
        # Toute tâche ajoutée depuis la dernière analyse doit être citée : sinon le texte est rejeté (repli déterministe).
        ajoutees = {int(x) for e in f["evolutions"] if "ajoutée" in e for x in re.findall(r"T-0*(\d+)", e)}
        cites = {int(x) for x in re.findall(r"T-0*(\d+)", txt)}
        if txt and len(txt.split()) <= 80 and not (T.numbers_in(txt) - T.numbers_in(json.dumps(f, ensure_ascii=False))) \
                and "relanc" not in txt.lower() and ajoutees <= cites:
            return txt, "llm"
    except Exception as e:
        log.warning("Synthèse LLM indisponible : %s", e)
    return synthese_deterministe(f), "fallback"


SYSTEM_CHAT = """Tu es le conseiller du haut responsable d'Arato, en français, pour le projet « {projet} » UNIQUEMENT. Tu t'appuies sur les
données réelles fournies par les outils (lister_tickets, lire_ticket, lire_historique_ticket, synthese_projet, charge_equipe).
Tu peux : répondre aux questions factuelles, donner ton AVIS argumenté sur la santé du projet, formuler des CONSEILS concrets et
priorisés, signaler de toi-même ce qui mérite attention (risques, tâches bloquantes, retards sans motif, déséquilibre de charge).
Pour un avis ou un conseil, structure la réponse : **Constat** (faits chiffrés), **Mon avis** (jugement clair et nuancé),
**Conseils** (2 à 4 actions concrètes, qui, quoi, pourquoi). Sinon réponds directement et de façon concise.
Ton professionnel : vouvoiement, phrases courtes, sans familiarité ni émoticônes. Ne calcule aucune date ni aucun retard : cite les chiffres
des outils. L'avancement est déclaré par le membre : écris « l'avancement déclaré est de X % ». Distingue toujours le fait (issu des
outils) de ton interprétation ; n'invente aucune cause (si aucun motif n'est documenté, dis-le et conseille de le demander).
Tu n'agis sur rien : tu conseilles, le responsable décide. Tu ne connais aucun autre projet. N'utilise jamais le mot « relance ».
Cite les tickets sous la forme T-014.
Règles métier à connaître : l'avancement (0, 25, 50, 75, 100 %) et le statut sont indépendants ; un ticket à 100 % n'est PAS fermé. Un ticket
ne peut être clôturé par le haut responsable que si son avancement CRM est à 100 % ET que tous ses critères d'acceptation sont cochés
(outil criteres_ticket : champ « cloturable »). Le retard est calculé par le programme en jours ouvrés, une tâche est en retard après
17 h le jour de l'échéance ; l'application ne reporte aucune échéance seule.
Un projet est TERMINÉ lorsque tous ses tickets sont fermés (infos_projet : projet_termine, tickets_fermes) ; une tâche déjà fermée n'est plus « à clôturer ».
Méthode : pour toute question sur une tâche, retrouve-la d'abord (chercher_ticket si l'utilisateur donne un titre ou des mots, lire_ticket
si tu as le numéro), puis réponds avec les données lues : membres, échéance, dépendances, critères. Pour une question d'ensemble, utilise
infos_projet. Pour « qui travaille sur… » ou « que fait Untel », utilise taches_du_membre. N'écris « je n'ai pas cette information » qu'après
avoir essayé les outils adaptés.
Reste STRICTEMENT sur la question : la première phrase y répond (oui/non, nombre, nom, date), puis au plus quelques lignes utiles ; n'ajoute ni bilan
général, ni conseils, ni autres tâches que si on te les demande.
Réponds D'ABORD à la question posée, sans réciter l'état du projet si on ne te le demande pas. Si on te demande qui tu es : présente-toi
en une ou deux phrases (agent IA de suivi d'Arato, conseiller du responsable pour ce projet) et dis ce que tu sais faire. Si la question
sort de ton domaine (culture générale, autre projet, code, météo, vie privée, décision RH…) ou si tu n'as pas la donnée, dis-le
franchement : « Cela dépasse mon champ de compétence » ou « Je n'ai pas cette information dans les données du projet », puis propose
ce que tu peux faire à la place. Ne devine jamais, n'invente rien."""


_PRESENTATION = ("Je suis l'**agent IA de suivi d'Arato** : le conseiller du responsable pour le projet « {projet} ». "
                 "Je lis les tickets, leurs échéances, leurs statuts et leur historique ; je calcule les retards avec le programme (jamais à l'estime) "
                 "et je m'appuie sur ces faits pour vous donner mon avis, des conseils et des alertes. Je n'agis sur rien : vous décidez.")
_CAPACITES = ("Vous pouvez me demander par exemple :\n- l'**état** du projet ou **mon avis** sur sa santé ;\n- les tâches **en retard** ou **à surveiller** ;\n"
              "- les **priorités** du moment et les **risques** à venir ;\n- la **charge** de l'équipe ;\n- pourquoi une tâche précise (ex. T-001) est dans cet état ;\n"
              "- des **conseils** pour tenir l'échéance.")
_HORS_CHAMP = ("Cela dépasse mon champ de compétence : je ne traite que le suivi du projet « {projet} » (tickets, échéances, retards, risques, charge de l'équipe).")


def _norm(q: str) -> str:
    import unicodedata
    q = unicodedata.normalize("NFD", q.lower())
    return "".join(c for c in q if unicodedata.category(c) != "Mn").replace("’", "'")


def chat_hors_sujet(projet: str, question: str, tickets: dict | None = None, strict: bool = False, noms: dict | None = None) -> dict | None:
    """Questions que le programme sait traiter sans modèle : présentation, salutations, remerciements, aide, et sujets hors compétence.
    Renvoie None quand la question concerne le suivi du projet."""
    q = _norm(question).strip()
    mots = re.findall(r"[a-z0-9']+", q)
    suivi = ("ticket", "tache", "projet", "retard", "echeance", "avancement", "risque", "priorit", "charge", "equipe", "membre", "statut",
             "synthese", "recommand", "conseil", "avis", "bilan", "sante", "bloqu", "dependance", "t-0", "planning", "delai",
             "critere", "accept", "cloture", "clotur", "ferme", "fermer", "termin", "fini", "livrable", "livraison", "assign", "affect",
             "travaille", "responsable", "deadline", "date", "jours", "pourcent", "combien", "quand", "qui ", "etat", "situation", "resume",
             "point sur", "alerte", "attente", "depend", "cahier", "ouvert", "nouveau", "en cours", "reste", "prevu", "objectif", "reunion",
             "recette", "analyse", "evaluation")
    mots_titres = {m for t in (tickets or {}).values() for m in re.findall(r"[a-z]{5,}", _norm(t.get("titre", "")))}
    mots_noms = {w for n in (noms or {}).values() for w in re.findall(r"[a-z]{3,}", _norm(n or ""))}
    vise_ticket = any(m in mots_titres or m in mots_noms for m in mots)   # la question reprend un mot d'un titre de tâche ou un nom de membre
    if re.search(r"\bt-?0*\d+\b", q) or vise_ticket or any(k in q for k in suivi):
        if not re.search(r"(qui es[- ]tu|tu es qui|qui etes[- ]vous|presente[- ]toi|c'est quoi ton|quel est ton nom|comment t'appelles)", q):
            return None
    if re.search(r"(qui es[- ]tu|tu es qui|qui etes[- ]vous|vous etes qui|presente[- ]toi|presentez[- ]vous|quel est ton nom|comment t'appelles|tu t'appelles|"
                 r"c'est quoi ton|tu es quoi|tu es un robot|es[- ]tu une ia|who are you)", q):
        return {"reponse": _PRESENTATION.format(projet=projet) + "\n\n" + _CAPACITES, "tickets_cites": []}
    if re.search(r"(que sais[- ]tu|que peux[- ]tu|tu peux faire|sais[- ]tu faire|a quoi sers|aide[- ]moi|comment (ca )?marche|que puis[- ]je te demander|tes capacites|help)", q):
        return {"reponse": "Voici ce que je peux faire pour le projet « " + projet + " » :\n\n" + _CAPACITES.split("\n\n")[0].replace("Vous pouvez me demander par exemple :", "").strip(), "tickets_cites": []}
    if len(mots) <= 4 and re.search(r"^(bonjour|bonsoir|salut|hello|coucou|hey|bjr)\b", q):
        return {"reponse": "Bonjour. Je suis l'agent de suivi du projet « " + projet + " ». Que souhaitez-vous savoir : l'état général, les retards, les priorités, les risques ou mon avis ?", "tickets_cites": []}
    if len(mots) <= 6 and re.search(r"(merci|thanks|parfait|super|d'accord|ok\b|tres bien|bien recu)", q):
        return {"reponse": "Avec plaisir. Je reste disponible si vous voulez un avis, des conseils ou le détail d'une tâche.", "tickets_cites": []}
    if re.search(r"(comment vas[- ]tu|ca va\b|tu vas bien)", q):
        return {"reponse": "Je fonctionne normalement, merci. Souhaitez-vous faire le point sur le projet « " + projet + " » ?", "tickets_cites": []}
    hors = ("meteo", "football", "match", "recette", "cuisine", "blague", "poeme", "chanson", "film", "horoscope", "bourse", "bitcoin", "election",
            "president", "capitale", "traduis", "traduire", "python", "javascript", "code ", "programme moi", "ecris-moi un", "ecris moi un", "equation", "histoire de")
    if any(k in q for k in hors):
        return {"reponse": _HORS_CHAMP.format(projet=projet) + "\n\n" + _CAPACITES, "tickets_cites": []}
    if strict and len(mots) >= 3 and not any(k in q for k in suivi):     # sans modèle : on ne devine pas ; avec le modèle, c'est lui qui juge
        return {"reponse": _HORS_CHAMP.format(projet=projet) + " Je n'ai pas non plus cette information dans les données du projet.\n\n" + _CAPACITES, "tickets_cites": []}
    return None


def _nom_t(tickets, i) -> str:
    return f"T-{i:03d} « {tickets[i]['titre']} »"


def _equipe(tickets, noms: dict, i) -> str:
    n = [noms.get(m) for m in (tickets[i].get("membre_ids") or []) if noms.get(m)]
    return " et ".join(n) if n else "le responsable de la tâche"


def chat_conseil(projet: str, question: str, tickets: dict[int, dict], tracking: dict[int, dict],
                 ctx: dict | None = None, hors_ligne: bool = False) -> dict:
    """Conseiller déterministe : répond aux demandes d'état, d'avis, de risques, de priorités, de charge et de conseils à partir des
    seuls faits calculés par Python. Sert de repli quand le modèle est indisponible ; ne contient jamais le mot « relance »."""
    hs = chat_hors_sujet(projet, question, tickets, strict=True, noms=(ctx or {}).get("noms"))
    if hs:
        return hs
    ctx = ctx or {}
    noms = ctx.get("noms") or {}
    q = question.lower()
    blocks = T.blocked_map(tickets)
    tard = sorted((i for i, tr in tracking.items() if tr["situation"] == "en_retard"), key=lambda i: -tracking[i]["jours_retard"])
    surv = [i for i, tr in tracking.items() if tr["situation"] == "a_surveiller"]
    att = [i for i, t in tickets.items() if t["statut"] == "en_attente" and i not in tard]
    ferm = [i for i, t in tickets.items() if t["statut"] == "ferme"]
    total = len(tickets)
    sans_alerte = total - len(tard) - len(surv)
    sante = round(100 * sans_alerte / total) if total else 100
    prio = ctx.get("priorites") or T.prioritize(tickets, tracking, blocks)
    cites: set[int] = set()

    def ref(i):
        cites.add(i)
        return _nom_t(tickets, i)

    def constat() -> str:
        bits = []
        if tard:
            bits.append(f"{len(tard)} tâche{'s' if len(tard) > 1 else ''} en retard ({', '.join(f'T-{i:03d}' for i in tard)})")
            cites.update(tard)
        if surv:
            bits.append(f"{len(surv)} à surveiller ({', '.join(f'T-{i:03d}' for i in surv)})")
            cites.update(surv)
        if att:
            bits.append(f"{len(att)} en attente")
        bits.append(f"{len(ferm)} terminée{'s' if len(ferm) > 1 else ''} sur {total}")
        return "**Constat** : " + ", ".join(bits) + "."

    def verdict() -> str:
        if sante >= 80:
            return "Le projet est globalement sous contrôle"
        if sante >= 50:
            return "Le projet demande de l'attention"
        return "Le projet est en difficulté"

    def avis() -> list[str]:
        out = [f"**Mon avis** : {verdict()} : {sante} % des tâches ne présentent aucune alerte."]
        bloq = [i for i in tard if blocks.get(i)]
        if bloq:
            i = bloq[0]
            out[0] += (f" Le point le plus préoccupant est {ref(i)} : en retard, elle retient "
                       f"{', '.join(f'T-{x:03d}' for x in blocks[i])}, donc le retard peut se propager.")
            cites.update(blocks[i])
        elif tard:
            out[0] += f" Le retard le plus ancien est {ref(tard[0])} ({tracking[tard[0]]['libelle'].lower()})."
        elif surv:
            out[0] += f" Rien n'est encore en retard, mais {ref(surv[0])} mérite un œil attentif."
        return out

    def conseils() -> list[str]:
        c: list[str] = []
        for i in tard[:2]:
            t = tickets[i]
            motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
            if blocks.get(i):
                c.append(f"Débloquez en premier {ref(i)} : demandez à {_equipe(tickets, noms, i)} une date de fin réaliste, car "
                         f"{len(blocks[i])} tâche{'s' if len(blocks[i]) > 1 else ''} en dépend{'ent' if len(blocks[i]) > 1 else ''}.")
            elif not motif:
                c.append(f"Faites documenter le motif du retard de {ref(i)} par {_equipe(tickets, noms, i)} : aucun motif n'est renseigné.")
            else:
                c.append(f"Faites le point sur {ref(i)} avec {_equipe(tickets, noms, i)} (motif connu : « {motif} ») et décidez d'un nouvel engagement de date.")
        for i in surv[:2]:
            tr = tracking[i]
            c.append(f"Confirmez avec {_equipe(tickets, noms, i)} que {ref(i)} tiendra son échéance : l'avancement déclaré est de "
                     f"{tr['avancement']} % et {tr['libelle'].split('(')[-1].rstrip(')')}.")
        if att:
            i = att[0]
            c.append(f"Levez le blocage de {ref(i)}, en attente : identifiez qui peut lever la contrainte et fixez-lui une date.")
        charge = ctx.get("charge") or []
        if charge and len(charge) > 1 and charge[0]["n"] >= charge[-1]["n"] + 3:
            h, b = charge[0], charge[-1]
            c.append(f"Rééquilibrez la charge : {h['nom']} porte {h['n']} tâches non terminées contre {b['n']} pour {b['nom']}.")
        if not c:
            c.append("Poursuivez le rythme actuel et gardez un œil sur les échéances des prochains jours.")
        return [f"{n}. {x}" for n, x in enumerate(c[:4], 1)]

    def risques() -> list[str]:
        r = ctx.get("risques") or []
        if not r:
            return ["**Risques** : aucun risque n'est identifié à ce jour."]
        out = ["**Risques anticipés** :"]
        for x in r[:4]:
            if x["id"] in tickets:
                niv = "élevé" if x.get("risque") == "eleve" else "modéré"
                out.append(f"- {ref(x['id'])} : risque {niv}. " + (x.get("prediction") or "").strip())
        return out

    def priorites() -> list[str]:
        if not prio:
            return ["**Priorités** : rien ne demande d'attention immédiate."]
        out = ["**À traiter en priorité** :"]
        for p in prio[:4]:
            if p["id"] in tickets:
                out.append(f"{p.get('rang', len(out))}. {ref(p['id'])} : " + ", ".join(p.get("raisons") or []) + ".")
        return out

    def charge_txt() -> list[str]:
        ch = ctx.get("charge") or []
        if not ch:
            return ["**Charge de l'équipe** : aucune donnée de charge disponible."]
        out = ["**Charge de l'équipe** (tâches non terminées) :"]
        out += [f"- {x['nom']} : {x['n']} tâche{'s' if x['n'] > 1 else ''}" + (f" dont {x['late']} en retard" if x["late"] else "") for x in ch[:6]]
        return out

    def liste(ids, titre) -> list[str]:
        if not ids:
            return [f"**{titre}** : aucune tâche."]
        return [f"**{titre}** :"] + [f"- {ref(i)} : {tracking[i]['libelle']}, avancement déclaré {tracking[i]['avancement']} %." for i in ids]

    has = lambda *k: any(x in q for x in k)
    parts: list[list[str]] = []
    mentions = [int(x) for x in re.findall(r"t-?0*(\d+)", q) if int(x) in tickets]

    def fiche(i: int) -> list[str]:
        t, tr = tickets[i], tracking[i]
        lig = [f"**{ref(i)}** : {tr['libelle']}. Statut {t['statut'].replace('_', ' ')}, avancement déclaré {tr['avancement']} %."]
        motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
        if tr["situation"] == "en_retard":
            lig.append(f"Motif connu : « {motif} »." if motif else "Aucun motif de retard n'est documenté : c'est la première chose à demander.")
        if blocks.get(i):
            lig.append("Elle retient " + ", ".join(f"T-{x:03d}" for x in blocks[i]) + " : son retard peut se propager.")
            cites.update(blocks[i])
        lig.append(f"Responsable : {_equipe(tickets, noms, i)}.")
        if t["statut"] != "ferme" and int(t.get("avancement_declare") or 0) >= 100:
            lig.append("Avancement à 100 % : " + ("tous les critères sont cochés, la clôture peut être validée." if (etats.get(i) or {}).get("cloturable")
                       else "la clôture attend que tous les critères d'acceptation soient cochés."))
        return [" ".join(lig[:2])] + lig[2:]

    etats = ctx.get("etats") or {}
    qn = _norm(question)
    generique = has("conseil", "recommand", "que faire", "avis", "risque", "priorit", "charge", "équipe", "equipe", "surveill", "retard",
                    "résum", "resum", "situation", "bilan", "santé", "sante", "état", "etat", "synth", "qui ")
    if not mentions and (not generique or has("critère", "critere", "accept")):   # tâche désignée par des mots de son titre (ex. « la recette API »)
        mots_q = {m for m in re.findall(r"[a-z]{5,}", qn)} - {"quels", "quelle", "quelles", "projet", "taches", "tache", "ticket", "critere", "criteres", "cloture"}
        score = {i: sum(m in _norm(t["titre"]) for m in mots_q) for i, t in tickets.items()}
        if score and max(score.values()) >= 1:
            meilleur = max(score.values())
            mentions = [i for i, n in score.items() if n == meilleur][:2]

    def criteres_txt(i: int) -> list[str]:
        e = etats.get(i) or T.etat_criteres(tickets[i].get("criteres_acceptation"), None, tickets[i]["titre"], tickets[i].get("description") or "", "", None,
                                           tickets[i]["statut"], tickets[i].get("avancement_declare"))
        ok = sum(e["criteres_valides"])
        out = [f"**Critères d'acceptation de {ref(i)}** ({ok} validé{'s' if ok > 1 else ''} sur {len(e['criteres_acceptation'])}) :"]
        out += [f"{n}. [{'x' if v else ' '}] {c}" for n, (c, v) in enumerate(zip(e["criteres_acceptation"], e["criteres_valides"]), 1)]
        av = tickets[i].get("avancement_declare")
        if tickets[i]["statut"] == "ferme":
            out.append("Le ticket est déjà fermé.")
        elif e["cloturable"]:
            out.append("L'avancement est à 100 % et tous les critères sont cochés : vous pouvez clôturer cette tâche.")
        else:
            manque = []
            if int(av or 0) < 100:
                manque.append(f"l'avancement déclaré est de {av} % (100 % requis)")
            if not e["tous_criteres_valides"]:
                manque.append("tous les critères ne sont pas cochés")
            out.append("Clôture impossible pour le moment : " + " et ".join(manque) + ".")
        return out

    def clotures_txt() -> list[str]:
        pretes = [i for i, e in etats.items() if e.get("cloturable")]
        presque = [i for i, t in tickets.items() if t["statut"] != "ferme" and int(t.get("avancement_declare") or 0) >= 100 and i not in pretes]
        out = []
        if ferm:
            out += fermees_txt()
        if pretes:
            out += ["**Prêtes à clôturer** (100 % et tous les critères cochés) :"] + [f"- {ref(i)}" for i in pretes]
        if presque:
            out += ["**À 100 % mais critères à cocher** :"] + [f"- {ref(i)}" for i in presque]
        if not pretes and not presque:
            out += ["Aucune autre tâche n'est prête à être clôturée : une tâche se clôture lorsque son avancement est à 100 % et que tous ses critères d'acceptation sont cochés."
                    if ferm else "Aucune tâche n'est prête à être clôturée : une tâche se clôture lorsque son avancement est à 100 % et que tous ses critères d'acceptation sont cochés."]
        return out

    def fermees_txt() -> list[str]:
        if not ferm:
            return ["**Tâches fermées** : aucune tâche n'est encore fermée."]
        if len(ferm) == total:
            return [f"**Le projet est terminé** : les {total} tâches sont fermées (clôturées)." if total > 1 else "**Le projet est terminé** : sa seule tâche est fermée."] + \
                   [f"- {ref(i)}" + (f" (fermée le {tickets[i]['date_fermeture']})" if tickets[i].get("date_fermeture") else "") for i in ferm[:12]]
        return [f"**Tâches fermées** : {len(ferm)} sur {total}."] + \
               [f"- {ref(i)}" + (f" (fermée le {tickets[i]['date_fermeture']})" if tickets[i].get("date_fermeture") else "") for i in ferm[:12]]

    membre = next((m for m, n in noms.items() if n and any(len(w) >= 3 and w in qn for w in _norm(n).split())), None)
    if has("critère", "critere", "accept") and mentions:
        parts = [criteres_txt(i) for i in dict.fromkeys(mentions)][:2]
    elif has("déjà", "deja", "clôturé", "cloturé", "clôturée", "cloturée", "fermé", "ferme ", "fermée", "fermées", "fermés", "terminé", "terminée", "terminées", "finie", "finies", "achevé", "projet est", "projet est-il") \
            and has("clôtur", "clotur", "ferm", "termin", "fini", "achev") and not has("peut", "prête", "prete", "pourr", "doit", "faut", "à clôturer", "a cloturer", "cloturable", "clôturable") and not mentions:
        parts = [fermees_txt()]
    elif has("clôtur", "clotur", "fermer", "ferm", "terminer", "finir") and not mentions:
        parts = [clotures_txt()]
    elif membre is not None and not mentions:
        ids = [i for i, t in tickets.items() if membre in (t.get("membre_ids") or [])]
        parts = [[f"**Tâches de {noms[membre]}** :"] + [f"- {ref(i)} : {tracking[i]['libelle']}, avancement déclaré {tracking[i]['avancement']} %." for i in ids]
                 if ids else [f"{noms[membre]} n'a aucune tâche dans ce projet."]]
    elif mentions:
        def ciblee(i: int) -> list[str] | None:
            """Réponse limitée à ce que la question demande sur une tâche précise (pas la fiche complète)."""
            t = tickets[i]
            if has("description", "de quoi", "c'est quoi", "consiste", "explique", "décris", "decris", "détail", "detail"):
                d = (t.get("description") or "").strip()
                return [f"**{ref(i)}** : " + (d if d else "aucune description n'est enregistrée pour cette tâche.")]
            if has("dépend", "depend", "bloque", "précède", "precede", "avant"):
                amont = [d for d in (t.get("depend_de_ids") or []) if d in tickets]
                aval = blocks.get(i) or []
                lig = [f"**{ref(i)}** :"]
                lig.append("Elle dépend de " + ", ".join(ref(d) for d in amont) + "." if amont else "Elle ne dépend d'aucune autre tâche.")
                lig.append("Elle retient " + ", ".join(f"T-{x:03d}" for x in aval) + "." if aval else "Elle ne retient aucune autre tâche.")
                cites.update(aval)
                return lig
            if has("qui ", "responsable", "assign", "affect", "membre", "travaille"):
                return [f"**{ref(i)}** est confiée à {_equipe(tickets, noms, i)}."]
            if has("échéance", "echeance", "quand", "délai", "delai", "date"):
                return [f"**{ref(i)}** : échéance le {t.get('echeance')} ({tracking[i]['libelle'].lower()})."]
            if has("statut", "avancement", "où en", "ou en", "progress"):
                return [f"**{ref(i)}** : statut « {t['statut'].replace('_', ' ')} », avancement déclaré {tracking[i]['avancement']} %."]
            return None
        parts = [(ciblee(i) or fiche(i)) for i in dict.fromkeys(mentions)][:3]
        if has("critère", "critere", "accept"):
            parts += [criteres_txt(mentions[0])]
        if has("conseil", "que faire", "comment", "faut"):
            i = mentions[0]
            parts.append(["**Conseil** : " + "faites le point avec " + _equipe(tickets, noms, i) + " et fixez une date de fin ferme."])
    elif has("toutes les tâches", "toutes les taches", "liste des tâches", "liste des taches", "liste de toutes", "quelles tâches", "quelles taches", "lister") \
            and not has("retard", "surveill", "attente", "ferm", "clôtur", "clotur", "critère", "critere"):
        parts = [["**Tâches du projet** :"] + [f"- {ref(i)} : {tickets[i]['statut'].replace('_', ' ')}, {tracking[i]['avancement']} %, {tracking[i]['libelle'].lower()}." for i in list(tickets)[:30]]
                 + ([f"… et {total - 30} autre(s)."] if total > 30 else [])]
    elif has("attente", "bloqué", "bloque", "bloquée", "bloquées", "bloqués"):
        att_all = [i for i, t in tickets.items() if t["statut"] == "en_attente"]
        if not att_all:
            parts = [["Non, aucune tâche n'est en attente."]]
        else:
            lig = [f"Oui, {len(att_all)} tâche{'s sont' if len(att_all) > 1 else ' est'} en attente :"]
            for i in att_all:
                motif = tickets[i].get("motif_attente_courant")
                lig.append(f"- {ref(i)} ({_equipe(tickets, noms, i)}) : " + (f"motif « {motif} »." if motif else "aucun motif documenté."))
            parts = [lig]
    elif has("combien", "nombre de", "répartition", "repartition", "par statut"):
        cnt: dict[str, int] = {}
        for t in tickets.values():
            cnt[t["statut"]] = cnt.get(t["statut"], 0) + 1
        lib = {"nouveau": "nouveau", "ouvert": "ouvert", "en_cours": "en cours", "en_attente": "en attente", "ferme": "fermé"}
        parts = [[f"Le projet compte **{total} tâche{'s' if total > 1 else ''}** : " + ", ".join(f"{n} {lib.get(k, k)}" for k, n in cnt.items()) +
                  f". {len(tard)} en retard, {len(surv)} à surveiller."]]
        cites.update(tard); cites.update(surv)
    elif any(k in qn for k in ("nouveau", "ouvert", "en cours", "commence", "demarre")) and not has("conseil"):
        cle_st = "en_cours" if "en cours" in qn else "nouveau" if "nouveau" in qn else "ouvert" if "ouvert" in qn else "en_cours"
        ids = [i for i, t in tickets.items() if t["statut"] == cle_st]
        nom_st = {"en_cours": "en cours", "nouveau": "nouveau", "ouvert": "ouvert"}[cle_st]
        parts = [([f"Oui, {len(ids)} tâche{'s sont' if len(ids) > 1 else ' est'} au statut « {nom_st} » :"] +
                  [f"- {ref(i)} : {tracking[i]['libelle']}, avancement déclaré {tracking[i]['avancement']} %." for i in ids[:12]])
                 if ids else [f"Non, aucune tâche n'est au statut « {nom_st} »."]]
    elif has("échéance", "echeance", "prochaine", "quand", "deadline", "date limite", "délai", "delai"):
        ouv = sorted((i for i, t in tickets.items() if t["statut"] != "ferme" and t.get("echeance")), key=lambda i: str(tickets[i]["echeance"]))
        parts = [(["**Prochaines échéances** :"] + [f"- {ref(i)} : {tracking[i]['libelle']} (échéance {tickets[i]['echeance']})." for i in ouv[:5]])
                 if ouv else ["Aucune échéance à venir : toutes les tâches sont fermées."]]
    elif has("avancement", "progress", "pourcent", "%"):
        ouv = [i for i, t in tickets.items() if t["statut"] != "ferme"]
        parts = [(["**Avancement déclaré** (tâches non fermées) :"] + [f"- {ref(i)} : {tracking[i]['avancement']} %." for i in ouv[:12]])
                 if ouv else ["Toutes les tâches sont fermées."]]
    elif has("conseil", "recommand", "que faire", "que dois", "comment", "améliorer", "décision", "décider", "agir"):
        parts = [[constat()], avis(), ["**Conseils** :"] + conseils()]
    elif has("avis", "pense", "évalu", "bilan", "santé", "sante", "sous contrôle", "inquiét", "tenir"):
        parts = [[constat()], avis(), ["**Conseils** :"] + conseils()[:2]]
    elif has("risque", "prédi", "predi", "anticip", "menace", "danger"):
        parts = risques() and [risques(), avis()]
    elif has("priorit", "traiter", "premier", "urgent", "commencer"):
        parts = [priorites()]
    elif has("charge", "équipe", "equipe", "membre", "surcharg", "répart", "repart", "qui travaille", "qui porte", "qui est"):
        parts = [charge_txt()]
    elif has("surveill"):
        parts = [liste(surv, "À surveiller")]
    elif has("retard"):
        parts = [liste(tard, "En retard")]
    elif has("résum", "resum", "situation", "point", "état", "etat", "synthèse", "synthese"):
        parts = [[constat()], avis()]
    elif has("état", "etat", "situation", "bilan", "point", "global", "ensemble", "où en", "ou en", "comment va", "tout va"):
        parts = [[constat()], avis()]
    else:      # question non reconnue : on ne plaque pas un rapport sans rapport avec la question
        parts = [["Je n'ai pas saisi précisément votre question. Reformulez-la avec une tâche (ex. T-040), un statut, une échéance ou un membre."],
                 [_CAPACITES]]
    texte = "\n\n".join("\n".join(b) for b in parts)
    if hors_ligne == "verif":
        texte += "\n\n_Réponse établie directement à partir des données calculées du projet (la réponse du modèle n'a pas pu être vérifiée)._"
    elif hors_ligne:
        texte += "\n\n_Réponse établie directement à partir des données calculées du projet (le modèle d'IA est momentanément indisponible)._"
    return {"reponse": texte, "tickets_cites": sorted(cites & set(tickets))}


def chat_fallback(projet: str, tickets: dict[int, dict], tracking: dict[int, dict]) -> str:  # conservé pour compatibilité
    tard = [i for i, tr in tracking.items() if tr["situation"] == "en_retard"]
    surv = [i for i, tr in tracking.items() if tr["situation"] == "a_surveiller"]
    out = [f"Le modèle d'IA est momentanément indisponible. Situation calculée du projet « {projet} » :"]
    out.append(f"En retard : {_tids(tard)}." if tard else "Aucune tâche en retard.")
    if surv:
        out.append(f"À surveiller : {_tids(surv)}.")
    return " ".join(out)


def chat_answer(projet: str, question: str, tickets: dict[int, dict], tracking: dict[int, dict],
                get_history: Callable, history: list[dict] | None = None, ctx: dict | None = None) -> dict:
    """Réponse du chat, limitée aux données du projet. Vérifie : chiffres issus des outils, tickets du projet seulement,
    absence du mot « relance » (une seule nouvelle tentative, puis repli déterministe)."""
    def lister(situation: str = ""):
        return [{"id": i, "titre": tickets[i]["titre"], **{k: tr[k] for k in ("statut", "situation", "libelle", "avancement")}}
                for i, tr in tracking.items() if not situation or tr["situation"] == situation]

    ctx = ctx or {}
    noms = ctx.get("noms") or {}
    etats = ctx.get("etats") or {}

    def fiche_ticket(i: int) -> dict:
        t = tickets[i]
        e = etats.get(i) or T.etat_criteres(t.get("criteres_acceptation"), None, t["titre"], t.get("description") or "", "", None,
                                           t["statut"], t.get("avancement_declare"))
        return {**{k: v for k, v in t.items() if k not in ("criteres_acceptation", "membre_ids", "depend_de_ids")},
                "membres": [noms.get(m, f"Membre {m}") for m in t.get("membre_ids") or []],
                "depend_de": [f"T-{d:03d} {tickets[d]['titre']}" for d in t.get("depend_de_ids") or [] if d in tickets],
                "retient": [f"T-{d:03d} {tickets[d]['titre']}" for d, o in tickets.items() if i in (o.get("depend_de_ids") or [])],
                "criteres_acceptation": [{"n": n, "texte": c, "valide": v} for n, (c, v) in enumerate(zip(e["criteres_acceptation"], e["criteres_valides"]), 1)],
                "cloturable": e["cloturable"], "clotur_possible_si": "avancement 100 % et tous les critères cochés"}

    def lire(ticket_id: int):
        if ticket_id not in tickets:
            return {"erreur": "Ticket absent du projet courant"}
        return {**fiche_ticket(ticket_id), "calculs_python": tracking[ticket_id]}

    def criteres_ticket(ticket_id: int):
        if ticket_id not in tickets:
            return {"erreur": "Ticket absent du projet courant"}
        e = etats.get(ticket_id) or {}
        f = fiche_ticket(ticket_id)
        return {"ticket_id": ticket_id, "titre": tickets[ticket_id]["titre"], "avancement_declare": tickets[ticket_id].get("avancement_declare"),
                "statut": tickets[ticket_id]["statut"], "criteres": f["criteres_acceptation"],
                "nb_valides": sum(c["valide"] for c in f["criteres_acceptation"]), "nb_criteres": len(f["criteres_acceptation"]),
                "criteres_par_defaut": bool(e.get("criteres_par_defaut")), "cloturable": f["cloturable"]}

    def chercher_ticket(texte: str):
        mots = {m for m in re.findall(r"[a-z0-9]{3,}", _norm(texte))}
        res = []
        for i, t in tickets.items():
            hay = _norm(f"{t['titre']} {t.get('description') or ''}")
            n = sum(m in hay for m in mots)
            if n:
                res.append((n, i))
        res.sort(key=lambda x: (-x[0], x[1]))
        return [{"id": i, "titre": tickets[i]["titre"], "statut": tickets[i]["statut"], "avancement": tickets[i].get("avancement_declare"),
                 "situation": tracking[i]["situation"], "membres": [noms.get(m, "?") for m in tickets[i].get("membre_ids") or []]}
                for _, i in res[:6]]

    def taches_du_membre(nom: str):
        n = _norm(nom)
        ids = [i for i, t in tickets.items() if any(n and n in _norm(noms.get(m, "")) for m in t.get("membre_ids") or [])]
        return [{"id": i, "titre": tickets[i]["titre"], "statut": tickets[i]["statut"], "avancement": tickets[i].get("avancement_declare"),
                 "situation": tracking[i]["situation"], "libelle": tracking[i]["libelle"]} for i in ids] or {"erreur": f"Aucune tâche trouvée pour « {nom} »"}

    def infos_projet():
        par_statut: dict[str, int] = {}
        for t in tickets.values():
            par_statut[t["statut"]] = par_statut.get(t["statut"], 0) + 1
        par_sit: dict[str, int] = {}
        for tr in tracking.values():
            par_sit[tr["situation"]] = par_sit.get(tr["situation"], 0) + 1
        av = [int(t.get("avancement_declare") or 0) for t in tickets.values()]
        return {"projet": projet, "echeance_finale": (ctx.get("projet_info") or {}).get("date_limite"), "nb_tickets": len(tickets),
                "par_statut": par_statut, "par_situation": par_sit,
                "avancement_declare_moyen": round(sum(av) / len(av)) if av else 0,
                "nb_fermes": sum(t["statut"] == "ferme" for t in tickets.values()),
                "tickets_fermes": [i for i, t in tickets.items() if t["statut"] == "ferme"],
                "projet_termine": bool(tickets) and all(t["statut"] == "ferme" for t in tickets.values()),
                "a_100_pourcent_non_fermes": [i for i, t in tickets.items() if t["statut"] != "ferme" and int(t.get("avancement_declare") or 0) >= 100],
                "pretes_a_cloturer": [i for i, e in etats.items() if e.get("cloturable")]}

    def hist(ticket_id: int):
        if ticket_id not in tickets:
            return {"erreur": "Ticket absent du projet courant"}
        return T.history_facts(get_history(ticket_id))

    hs = chat_hors_sujet(projet, question, tickets, noms=noms)
    if hs:
        return hs

    def synthese_projet():
        return {"priorites": ctx.get("priorites", []), "risques_et_predictions": ctx.get("risques", []),
                "recommandations_ouvertes": ctx.get("recos", []), "evolutions_recentes": ctx.get("evolutions", [])}

    def charge_equipe():
        return ctx.get("charge", [])

    sit = {"type": "object", "properties": {"situation": {"type": "string",
           "enum": ["", "en_retard", "a_surveiller", "normale", "ferme"]}}}
    tid = {"type": "object", "properties": {"ticket_id": {"type": "integer"}}, "required": ["ticket_id"]}
    tool_list = [Tool("lister_tickets", "Liste des tickets du projet avec situation calculée par Python.", sit, lister),
                 Tool("lire_ticket", "Détail d'un ticket du projet et calculs Python.", tid, lire),
                 Tool("lire_historique_ticket", "Historique des statuts, avancements et motifs d'un ticket.", tid, hist),
                 Tool("synthese_projet", "Priorités ordonnées, risques et prédictions, recommandations ouvertes et évolutions récentes du projet.",
                      {"type": "object", "properties": {}}, synthese_projet),
                 Tool("charge_equipe", "Charge de chaque membre : tâches non terminées et en retard.",
                      {"type": "object", "properties": {}}, charge_equipe),
                 Tool("criteres_ticket", "Critères d'acceptation d'un ticket, lesquels sont cochés, et s'il est clôturable (100 % + tous cochés).", tid, criteres_ticket),
                 Tool("chercher_ticket", "Retrouve des tickets du projet à partir de mots du titre ou de la description.",
                      {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]}, chercher_ticket),
                 Tool("taches_du_membre", "Tâches d'un membre de l'équipe, à partir de son nom ou prénom.",
                      {"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]}, taches_du_membre),
                 Tool("infos_projet", "Vue d'ensemble : échéance finale, nombre de tickets par statut et par situation, avancement moyen, tickets à 100 % et clôturables.",
                      {"type": "object", "properties": {}}, infos_projet)]
    system = SYSTEM_CHAT.format(projet=projet)
    connus = {*tickets}
    prev_nums = {n for h in (history or []) for n in T.numbers_in(h.get("content") or "")}
    consigne = ""
    sorties: list[str] = []          # sorties d'outils cumulées sur les deux tentatives
    ids_projet = {*tickets}          # les identifiants de tickets du projet sont des références valides
    for _ in range(2):
        r = run_agent(system + consigne, question, tool_list, max_iter=6, history=history, max_tokens=1100)
        sorties += r["trace"]
        rep = (r["text"] or "").strip()
        if not rep:
            break
        autorises = (T.numbers_in(" ".join(sorties)) | T.numbers_in(question) | prev_nums | ids_projet
                     | set(range(0, len(tickets) + 1)) | {25, 50, 75, 100})      # comptages et paliers d'avancement usuels
        cites = {int(x) for x in re.findall(r"T-0*(\d+)", rep)}
        erreurs = []
        if "relanc" in rep.lower():
            erreurs.append("n'utilise pas le mot « relance »")
        if T.numbers_in(rep) - autorises:
            erreurs.append("n'écris que des chiffres présents dans les résultats des outils")
        if cites - connus:
            erreurs.append("ne cite que des tickets du projet courant")
        if not erreurs:
            return {"reponse": rep, "tickets_cites": sorted(cites & connus)}
        consigne = "\nCorrection obligatoire : " + " ; ".join(erreurs) + "."
    return chat_conseil(projet, question, tickets, tracking, ctx, hors_ligne="verif")
