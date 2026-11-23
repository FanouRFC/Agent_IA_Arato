"""Audit v18 : critères d'acceptation, pas de clôture à 100 %, sécurité de connexion, compatibilité LLM local (Ollama simulé par
tests/fake_ollama.py : de vrais appels HTTP, mais PAS un vrai modèle).
Lancer : cd Backend_AgentIA && python -m pytest tests -q"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi import HTTPException  # noqa: E402

from app import agent, llm, security, settings_store, tools as T  # noqa: E402
from app.config import settings  # noqa: E402
from tests.fake_ollama import FakeOllama  # noqa: E402

CTX = ("Le portail client permet de se connecter avec e-mail et mot de passe. La session expire après 30 minutes d'inactivité. "
       "Export PDF des factures.")


# ---------- P2 : critères d'acceptation ----------
def test_criteres_ecartent_generiques_inventes_et_hors_sujet():
    ok, ko = T.validate_criteria([
        "1. Le client peut se connecter avec son e-mail et son mot de passe.",
        "La session expire après 45 minutes d'inactivité.",          # 45 absent du document
        "Le travail est terminé et conforme aux attentes.",           # générique
        "Un lecteur de cartes bancaires est installé.",               # sans lien
        "Le client peut se connecter avec son e-mail et mot de passe.",   # doublon
        "L'export des factures est disponible au format PDF."], CTX)
    assert ok == ["Le client peut se connecter avec son e-mail et son mot de passe.", "L'export des factures est disponible au format PDF."]
    assert len(ko) == 4


def test_nettoyage_saisie_humaine():
    assert T.clean_criteria([" - Un ", "• Le champ est obligatoire", "Le champ est obligatoire", {"texte": "Message affiché"}]) == \
        ["Le champ est obligatoire", "Message affiché"]
    assert T.clean_criteria(None) == []


def _taches():
    return [{"id": 1, "titre": "Connexion", "description": "Connexion du client", "source_dans_document": "Le portail client permet de se connecter avec e-mail et mot de passe.", "ambiguites": []},
            {"id": 2, "titre": "Rapports", "description": "", "source_dans_document": "Introuvable dans le texte", "ambiguites": []}]


def test_generation_de_criteres_sans_information_suffisante(monkeypatch):
    """Le modèle ne propose rien de fondé pour la tâche 2 : les critères inventés sont écartés et la tâche reçoit des critères PAR DÉFAUT
    (tirés de son énoncé, sans fait inventé) : une tâche a toujours des critères."""
    def faux(messages, **k):
        return {"content": '{"criteres":[{"id":1,"criteres_acceptation":["Le client peut se connecter avec e-mail et mot de passe.","Le système fonctionne correctement."]},'
                           '{"id":2,"criteres_acceptation":["Le rapport contient 12 colonnes."]}]}'}
    monkeypatch.setattr(llm, "chat", faux)
    taches = _taches()
    bilan = agent.generer_criteres(taches, CTX)
    assert taches[0]["criteres_acceptation"] == ["Le client peut se connecter avec e-mail et mot de passe."]
    assert 1 <= len(taches[1]["criteres_acceptation"]) <= 3 and not any("12" in c for c in taches[1]["criteres_acceptation"])
    assert any("par défaut" in a for a in taches[1]["ambiguites"])
    assert bilan == {"avec": 1, "sans": 1, "erreur": None}


def test_generation_de_criteres_modele_indisponible(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("serveur injoignable")))
    taches = _taches()
    bilan = agent.generer_criteres(taches, CTX)
    assert bilan["erreur"] and all(1 <= len(t["criteres_acceptation"]) <= 3 for t in taches)
    assert any("par défaut" in a for a in taches[0]["ambiguites"])


# ---------- P1 : avancement et statut indépendants ----------
def _t(statut="en_cours", av=100, ech="2026-10-28"):
    return {"id": 14, "statut": statut, "avancement_declare": av, "echeance": ech, "date_fermeture": None}


def test_cent_pour_cent_non_ferme_est_signale_pas_cloture():
    now = dt.datetime(2026, 10, 30, 10, 0)
    tr = T.compute_tracking(_t(), now, frozenset())
    assert tr["situation"] == "en_retard" and tr["cloture_a_valider"] and tr["jours_retard"] == 2     # le retard continue tant que non fermé
    texte, diag = T.recommendation_fallback(_t(), tr, None, {})
    assert texte.startswith("T-014 :") and "valider sa clôture" in texte and "relanc" not in texte.lower()
    assert not T.check_recommendation(texte, 14, {14, 100, 2})
    assert not T.compute_tracking(_t("ferme"), now, frozenset())["cloture_a_valider"]
    assert not T.compute_tracking(_t(av=75), now, frozenset())["cloture_a_valider"]


# ---------- P3 : calcul des retards (jours ouvrés) ----------
@pytest.mark.parametrize("now,attendu", [
    (dt.datetime(2026, 10, 15, 10), (True, 3)),       # échéance lundi 12, jeudi 15 → 3 jours ouvrés (exemple du cahier des charges)
    (dt.datetime(2026, 10, 12, 16, 59), (False, 0)),
    (dt.datetime(2026, 10, 12, 17, 0), (True, 0)),    # 17h00 le jour de l'échéance
    (dt.datetime(2026, 10, 17, 9), (True, 4)),        # samedi : 13, 14, 15, 16 comptés, pas le week-end
])
def test_jours_de_retard(now, attendu):
    tr = T.compute_tracking({"id": 1, "statut": "en_cours", "avancement_declare": 50, "echeance": "2026-10-12"}, now, frozenset())
    assert (tr["est_en_retard"], tr["jours_retard"]) == attendu


def test_en_attente_depassee_compte_en_retard_et_garde_son_statut():
    tr = T.compute_tracking({"id": 1, "statut": "en_attente", "avancement_declare": 50, "echeance": "2026-10-26"}, dt.datetime(2026, 10, 28, 9), frozenset())
    assert tr["est_en_retard"] and tr["jours_retard"] == 2 and tr["statut"] == "en_attente"


# ---------- P4 : sécurité ----------
def test_limitation_des_essais_de_connexion():
    lim = security.LimiteConnexion()
    for _ in range(lim.MAX):
        lim.verifier("ip|a@b.c")
        lim.echec("ip|a@b.c")
    with pytest.raises(HTTPException) as e:
        lim.verifier("ip|a@b.c")
    assert e.value.status_code == 429
    lim.verifier("ip|autre@b.c")           # un autre compte n'est pas bloqué
    lim.succes("ip|a@b.c")
    lim.verifier("ip|a@b.c")


def test_empreinte_illisible_refusee_sans_erreur():
    assert security.verify_password("x", "pas-une-empreinte") is False
    assert security.verify_password("secret", security.hash_password("secret")) is True


# ---------- P5 : LLM local (Ollama simulé) ----------
@pytest.fixture()
def ollama(monkeypatch):
    with FakeOllama() as srv:
        monkeypatch.setattr(settings, "llm_base_url", srv.url)
        monkeypatch.setattr(settings, "llm_api_key", "")
        monkeypatch.setattr(settings, "llm_timeout", 10)
        monkeypatch.setattr(llm, "current_model", lambda: "llama3.1:8b")
        yield srv


def test_fournisseur_local_sans_cle(ollama):
    p = llm.provider()
    assert p["local"] and p["cle_configuree"]
    assert llm.list_models() == ["llama3.1:8b", "qwen2.5:7b-instruct"]


def test_verification_complete_ok(ollama):
    r = llm.verifier()
    assert r["ok"] and [e["etape"] for e in r["etapes"]] == ["serveur", "modele", "generation"] and r["reponse"] == "OK"


def test_modele_non_installe_message_explicite(ollama, monkeypatch):
    monkeypatch.setattr(llm, "current_model", lambda: "mistral:7b")
    with pytest.raises(llm.LLMError, match="ollama pull mistral:7b"):
        llm.verifier()
    with pytest.raises(llm.LLMError, match="ollama pull"):
        llm.chat([{"role": "user", "content": "x"}])           # 404 du serveur


def test_modele_sans_outils_repli_automatique(ollama):
    ollama.tools_supported = False
    msg = llm.chat([{"role": "user", "content": "x"}], tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}])
    assert msg["content"] and "tools" not in ollama.requetes[-1] and "tools" in ollama.requetes[-2]


def test_serveur_local_arrete(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:9/v1")      # port fermé
    with pytest.raises(llm.LLMError, match="ollama serve"):
        llm.chat([{"role": "user", "content": "x"}])
    with pytest.raises(llm.LLMError, match="injoignable"):
        llm.list_models()


def test_modele_choisi_lie_au_fournisseur(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Setting
    eng = create_engine("sqlite://")
    Setting.__table__.create(eng)
    with sessionmaker(eng)() as db:
        monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
        monkeypatch.setattr(settings, "llm_model", "env-model")
        settings_store.put(db, "llm_model", "llama-3.3-70b-versatile")
        settings_store.put(db, "llm_model_fournisseur", llm.fournisseur_cle())
        assert settings_store.params(db)["llm_model"] == "llama-3.3-70b-versatile"
        monkeypatch.setattr(settings, "llm_base_url", "http://localhost:11434/v1")      # bascule vers Ollama
        assert settings_store.params(db)["llm_model"] == "env-model"


def test_creation_de_taches_et_criteres_via_ollama(ollama):
    doc = ("Cahier des charges Portail\n\n• Le portail client permet de se connecter avec e-mail et mot de passe.\n"
           "• Importer un fichier PDF de factures et en extraire le contenu proprement.\n")
    res = agent.create_tasks(doc, {"membres": [], "profils": [], "tickets": []})
    assert res and len(res["taches"]) >= 2
    assert all(t["criteres_acceptation"] for t in res["taches"])
    assert all(T._norm(t["source_dans_document"]) in T._norm(doc) for t in res["taches"])
