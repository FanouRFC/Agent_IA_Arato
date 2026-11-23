"""Affectation automatique : l'IA propose, ce code garantit des propositions complètes et équilibrées.

Règles (déterministes) :
- chaque tâche reçoit au moins 1 membre ; une tâche longue ou pluridisciplinaire en reçoit 2 ou 3 (multi-affectation) ;
- le nombre visé est `nb_membres_recommande` (proposé par l'IA) ; à défaut : 1 membre si durée < 5 jours, 2 sinon ;
- les propositions valides de l'IA sont conservées ; on complète avec les profils les plus proches puis la charge la plus faible ;
- un membre n'apparaît jamais deux fois sur la même tâche ; la charge est mise à jour au fil de l'eau (équilibrage)."""
import re
import unicodedata

NB_MAX = 3


def _mots(s: str) -> set[str]:
    s = unicodedata.normalize("NFD", (s or "").lower().replace("-", ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return {m for m in re.split(r"[^a-z0-9]+", s) if len(m) >= 3}


def nombre_vise(t: dict, nb_membres: int) -> int:
    nb = t.get("nb_membres_recommande")
    if not isinstance(nb, int) or not 1 <= nb <= NB_MAX:
        nb = 2 if int(t.get("duree_estimee_jours") or 1) >= 5 else 1
    return max(1, min(nb, nb_membres, NB_MAX))


def affecter(taches: list[dict], membres: list[dict], tickets: list[dict]) -> list[dict]:
    """Complète `membre_ids_proposes` de chaque tâche."""
    if not membres:
        return taches
    ids = {m["id"] for m in membres}
    profils = {m["id"]: _mots(m["profil"]) for m in membres}
    charge = {i: 0 for i in ids}
    for t in tickets:                                     # charge actuelle : tickets non fermés
        if t.get("statut") != "ferme":
            for i in t.get("membre_ids", []):
                if i in charge:
                    charge[i] += 1
    for t in taches:
        prop = list(dict.fromkeys(i for i in (t.get("membre_ids_proposes") or []) if i in ids))   # valides, sans doublon
        visees = max(nombre_vise(t, len(ids)), min(len(prop), NB_MAX))
        prop = prop[:NB_MAX]
        voulu = _mots(t.get("profil_recommande", ""))
        while len(prop) < visees:
            restants = [i for i in ids if i not in prop]
            if not restants:
                break
            # profil le plus proche d'abord ; puis charge la plus faible ; puis identifiant (résultat reproductible)
            prop.append(min(restants, key=lambda i: (-len(voulu & profils[i]), charge[i], i)))
        t["membre_ids_proposes"] = prop
        for i in prop:
            charge[i] += 1
    return taches
