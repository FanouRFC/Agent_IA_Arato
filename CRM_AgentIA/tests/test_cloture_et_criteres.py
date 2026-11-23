"""CRM : l'avancement à 100 % ne ferme jamais un ticket ; la clôture est une décision du haut responsable (clé de service) ;
les critères d'acceptation sont enregistrés et relus. Base dédiée « arato_crm_test » (jamais la base de démonstration).
Lancer : cd CRM_AgentIA && CRM_DATABASE_URL=postgresql+psycopg2://arato:arato@localhost:5432/arato_crm_test python -m pytest tests -q"""
import datetime as dt
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("CRM_DATABASE_URL", "postgresql+psycopg2://arato:arato@localhost:5432/arato_crm_test")
os.environ["CRM_SERVICE_KEY"] = "cle-de-test-service"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Base, Evenement, engine  # noqa: E402

assert "arato_crm_test" in str(engine.url), "ces tests réinitialisent la base : base de test uniquement"
SVC = {"X-Service-Key": "cle-de-test-service"}


@pytest.fixture()
def crm():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:                       # lifespan : création des tables + migration
        pid = c.post("/projets", headers=SVC, json={"nom": "Projet test"}).json()["id"]
        m = c.post("/membres", json={"nom": "Faly Test", "profil": "Dev", "email": "faly@arato.test"}).json()["id"]
        c.ctx = {"pid": pid, "mid": m}
        yield c


def creer(c, **kw):
    corps = {"titre": "Ticket A", "projet_id": c.ctx["pid"], "echeance": str(dt.date.today() + dt.timedelta(days=5)),
             "membre_ids": [c.ctx["mid"]], **kw}
    return c.post("/tickets", headers=SVC, json=corps).json()


def passer_en_cours(c, t):
    r = c.put(f"/tickets/{t['id']}/statut", json={"statut": "en_cours", "auteur_id": c.ctx["mid"]})
    assert r.status_code == 200, r.text


def test_100_pour_cent_ne_ferme_pas_le_ticket(crm):
    t = creer(crm)
    passer_en_cours(crm, t)
    for v in (50, 75, 100):
        r = crm.put(f"/tickets/{t['id']}/avancement", json={"avancement": v, "auteur_id": crm.ctx["mid"]})
        assert r.status_code == 200
    lu = crm.get(f"/tickets/{t['id']}").json()
    assert lu["avancement_declare"] == 100 and lu["statut"] == "en_cours" and lu["date_fermeture"] is None


def test_un_membre_ne_peut_pas_fermer(crm):
    t = creer(crm)
    passer_en_cours(crm, t)
    crm.put(f"/tickets/{t['id']}/avancement", json={"avancement": 100, "auteur_id": crm.ctx["mid"]})
    r = crm.put(f"/tickets/{t['id']}/statut", json={"statut": "ferme", "auteur_id": crm.ctx["mid"]})
    assert r.status_code == 409 and "haut responsable" in r.json()["detail"]
    assert crm.get(f"/tickets/{t['id']}").json()["statut"] == "en_cours"


def test_cloture_reservee_au_connecteur(crm):
    t = creer(crm)
    passer_en_cours(crm, t)
    assert crm.put(f"/tickets/{t['id']}/cloture", json={"valide_par": "resp@arato.mg"}).status_code == 403
    assert crm.put(f"/tickets/{t['id']}/cloture", headers={"X-Service-Key": "mauvaise"}, json={"valide_par": "resp@arato.mg"}).status_code == 403
    assert crm.get(f"/tickets/{t['id']}").json()["statut"] == "en_cours"


def test_cloture_validee_ferme_et_ne_se_rejoue_pas(crm):
    t = creer(crm)
    passer_en_cours(crm, t)
    r = crm.put(f"/tickets/{t['id']}/cloture", headers=SVC, json={"valide_par": "resp@arato.mg"})
    assert r.status_code == 200 and r.json()["statut"] == "ferme" and r.json()["date_fermeture"] == str(dt.date.today())
    assert crm.put(f"/tickets/{t['id']}/cloture", headers=SVC, json={"valide_par": "resp@arato.mg"}).status_code == 409
    from app.models import SessionLocal
    with SessionLocal() as db:       # événement de source « service » : pas d'écho vers le suivi
        ev = [e for e in db.scalars(select(Evenement).where(Evenement.ticket_id == t["id"], Evenement.type == "changement_statut"))]
    assert ev and ev[-1].source == "service"


def test_criteres_enregistres_et_relus(crm):
    t = creer(crm, criteres_acceptation=["  Le client peut se connecter.  ", "", "L'export PDF est disponible."])
    assert t["criteres_acceptation"] == ["Le client peut se connecter.", "L'export PDF est disponible."]
    assert crm.get(f"/tickets/{t['id']}").json()["criteres_acceptation"] == t["criteres_acceptation"]
    assert creer(crm)["criteres_acceptation"] == []
    r = crm.post("/tickets", headers=SVC, json={"titre": "X", "projet_id": crm.ctx["pid"], "echeance": "2027-01-01", "criteres_acceptation": ["a" * 401]})
    assert r.status_code == 422


def test_migration_idempotente(crm):
    from app.main import migrer
    migrer()
    migrer()
