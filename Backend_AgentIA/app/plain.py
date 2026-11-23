"""Vulgarisation des chiffres du projet : un verdict et quelques phrases que n'importe qui comprend.
Tout est calculé par Python (aucun appel au LLM) : mêmes chiffres que le tableau de bord, jamais d'invention."""
import datetime as dt

from .calendar_utils import bd_between


def _pl(n: int, un: str, plusieurs: str) -> str:
    return un if n == 1 else plusieurs


def en_clair(tickets: dict, tracking: dict, holidays=frozenset(), today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    n = len(tickets)
    if not n:
        return {"niveau": "vide", "titre": "Projet sans tâche", "phrase": "Aucun ticket n'a encore été créé pour ce projet.",
                "progression": 0, "fermees": 0, "total": 0, "chiffres": [], "fin_prevue": None, "jours_avant_fin": None,
                "prochaine": None}
    sit = lambda s: [i for i, tr in tracking.items() if tr["situation"] == s]
    retard, surv = sit("en_retard"), sit("a_surveiller")
    fermees = [i for i, t in tickets.items() if t["statut"] == "ferme"]
    attente = [i for i, t in tickets.items() if t["statut"] == "en_attente" and i not in retard]
    rails = [i for i in tickets if i not in retard and i not in surv and i not in fermees]
    prog = round(sum(100 if t["statut"] == "ferme" else t["avancement_declare"] for t in tickets.values()) / n)

    if len(fermees) == n:
        niveau, titre = "termine", "Projet terminé"
        phrase = f"Les {n} tâches sont terminées. Bravo : il ne reste plus rien à suivre."
    elif retard:
        niveau, titre = "tendu", "Projet sous tension"
        k = len(retard)
        phrase = (f"{k} {_pl(k, 'tâche est', 'tâches sont')} en retard sur {n} : {_pl(k, 'elle aurait', 'elles auraient')} "
                  "déjà dû être terminée" + ("" if k == 1 else "s") + ". C'est ce qui demande votre attention en premier.")
    elif surv:
        k = len(surv)
        niveau, titre = "vigilance", "Projet à surveiller"
        phrase = (f"Aucun retard pour l'instant, mais {k} {_pl(k, 'tâche approche', 'tâches approchent')} de "
                  f"{_pl(k, 'son', 'leur')} échéance sans avoir beaucoup avancé.")
    else:
        niveau, titre = "serein", "Projet sous contrôle"
        phrase = "Tout avance dans les délais : aucune tâche en retard ni proche de l'être."

    vivants = {i: tr for i, tr in tracking.items() if tr["situation"] != "ferme"}
    fin = max((t["echeance"] for t in tickets.values()), default=None)
    fin_d = dt.date.fromisoformat(str(fin)) if fin else None
    avant_fin = bd_between(today, fin_d, holidays) if fin_d and fin_d > today and len(fermees) < n else None
    prochaine = None
    for i, tr in sorted(vivants.items(), key=lambda x: (x[1]["echeance"], x[0])):
        if tr["situation"] != "en_retard":
            prochaine = {"id": i, "titre": tickets[i]["titre"], "echeance": tr["echeance"], "jours": tr["jours_restants"]}
            break

    chiffres = [
        {"cle": "progression", "valeur": f"{prog} %", "libelle": "du travail est fait",
         "explication": f"Moyenne de l'avancement déclaré sur les {n} tâches ({len(fermees)} {_pl(len(fermees), 'terminée', 'terminées')})."},
        {"cle": "retard", "valeur": len(retard), "libelle": _pl(len(retard), "tâche en retard", "tâches en retard"),
         "explication": "L'échéance est passée et la tâche n'est pas terminée."},
        {"cle": "surveiller", "valeur": len(surv), "libelle": _pl(len(surv), "à surveiller", "à surveiller"),
         "explication": "Pas encore en retard, mais l'échéance est très proche et l'avancement faible."},
        {"cle": "rails", "valeur": len(rails), "libelle": _pl(len(rails), "dans les délais", "dans les délais"),
         "explication": "Ces tâches suivent leur calendrier" + (f" (dont {len(attente)} en attente d'un retour)." if attente else ".")},
    ]
    return {"niveau": niveau, "titre": titre, "phrase": phrase, "progression": prog, "fermees": len(fermees), "total": n,
            "chiffres": chiffres, "fin_prevue": fin_d.isoformat() if fin_d else None, "jours_avant_fin": avant_fin,
            "prochaine": prochaine}

