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


def _modele_actif(db) -> str:
    """Modèle choisi dans l'administration, SEULEMENT s'il a été choisi pour le fournisseur configuré actuellement (LLM_BASE_URL).
    Après un changement de fournisseur (ex. Groq → Ollama), le modèle du fichier .env s'applique : plus de « modèle introuvable »."""
    from .llm import fournisseur_cle
    choisi = get(db, "llm_model", None)
    if choisi and get(db, "llm_model_fournisseur", None) == fournisseur_cle():
        return choisi
    return settings.llm_model


def params(db) -> dict:
    hol = get(db, "jours_feries", [h.strip() for h in settings.holidays.split(",") if h.strip()])
    h, m = settings.work_day_end.split(":")
    return {
        "seuil_jours": int(get(db, "seuil_jours", settings.seuil_jours)),
        "seuil_avancement": int(get(db, "seuil_avancement", settings.seuil_avancement)),
        "jours_feries": hol,
        "holidays": {dt.date.fromisoformat(x) for x in hol},
        "work_end": dt.time(int(h), int(m)),
        "llm_model": _modele_actif(db),
    }
