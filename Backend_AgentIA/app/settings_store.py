"""Paramètres modifiables dans l'administration (seuils, jours fériés, modèle d'IA)."""
import datetime as dt

from .config import settings
from .models import Setting


def get(db, cle, default=None):
    row = db.get(Setting, cle)
    return row.valeur["v"] if row else default


def put(db, cle, valeur):
    row = db.get(Setting, cle)
    if row:
        row.valeur = {"v": valeur}
    else:
        db.add(Setting(cle=cle, valeur={"v": valeur}))
    db.commit()


def params(db) -> dict:
    hol = get(db, "jours_feries", [h.strip() for h in settings.holidays.split(",") if h.strip()])
    h, m = settings.work_day_end.split(":")
    return {
        "seuil_jours": int(get(db, "seuil_jours", settings.seuil_jours)),
        "seuil_avancement": int(get(db, "seuil_avancement", settings.seuil_avancement)),
        "jours_feries": hol,
        "holidays": {dt.date.fromisoformat(x) for x in hol},
        "work_end": dt.time(int(h), int(m)),
        "llm_model": get(db, "llm_model", settings.llm_model),
    }
