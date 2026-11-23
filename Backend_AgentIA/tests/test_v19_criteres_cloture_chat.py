"""v19 : critères toujours proposés, clôture conditionnée (100 % ET tous les critères cochés), chat plus pertinent.
Les endpoints sont appelés directement avec une base SQLite en mémoire et un CRM factice (aucun réseau, aucun modèle réel)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import agent, api, db as appdb, llm, models, tools as T  # noqa: E402


# ---------- critères par défaut ----------
def test_criteres_par_defaut_toujours_1_a_3():
    for titre, desc, src in [("Rapports", "", ""), ("Connexion", "Connexion du client par e-mail", ""), ("X", "", "Le client se connecte.")]:
        c = T.criteres_par_defaut(titre, desc, src)
        assert 1 <= len(c) <= 3 and all(len(x) >= 20 for x in c)
        assert c == T.criteres_par_defaut(titre, desc, src)                   # stable : les cases cochées restent attachées au texte
        assert not any(ch.isdigit() for ch in "".join(c))                     # aucun chiffre inventé


def test_assurer_criteres_conserve_ceux_existants():
    assert T.assurer_criteres(["Le champ est obligatoire"], "T", "")[0] == ["Le champ est obligatoire"]
    c, defaut = T.assurer_criteres([], "T", "")
    assert defaut and c


def test_generation_jamais_vide_meme_si_le_modele_repond_n_importe_quoi(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "désolé je ne sais pas"})
    taches = [{"id": 1, "titre": "Module", "description": "", "source_dans_document": "", "ambiguites": []}]
    agent.generer_criteres(taches, "texte")
    assert 1 <= len(taches[0]["criteres_acceptation"]) <= 3


# ---------- état et clôture ----------
def _etat(avancement, coches, statut="en_cours", crit=("A fait.", "B fait.")):
    return T.etat_criteres(list(crit), None, "Titre", "", "", coches, statut, avancement)


def test_cloturable_seulement_a_100_et_tous_coches():
    assert _etat(100, {"A fait.", "B fait."})["cloturable"] is True
    assert _etat(100, {"A fait."})["cloturable"] is False            # un critère manque
    assert _etat(75, {"A fait.", "B fait."})["cloturable"] is False  # pas à 100 %
    assert _etat(0, set())["cloturable"] is False                    # tâche non commencée : jamais
    assert _etat(100, {"A fait.", "B fait."}, statut="ferme")["cloturable"] is False


class CrmFactice:
    def __init__(self, avancement, statut="en_cours"):
        self.t = {"id": 7, "titre": "Tâche 7", "description": "", "statut": statut, "avancement_declare": avancement,
                  "criteres_acceptation": ["A fait.", "B fait."], "membre_ids": [], "depend_de_ids": []}
        self.fermes = []

    def get_ticket(self, tid):
        return self.t

    def cloturer(self, tid, par):
        self.fermes.append(tid)


@pytest.fixture()
def base(monkeypatch):
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    appdb.Base.metadata.create_all(eng)
    monkeypatch.setattr(api, "log_action", lambda *a, **k: None)
    monkeypatch.setattr(api.service, "reevaluate", lambda *a, **k: None)
    monkeypatch.setattr(api.projects, "of_ticket", lambda db, t: type("P", (), {"id": 1})())
    with Session(eng) as s:
        yield s


def _crm(monkeypatch, avancement, statut="en_cours"):
    c = CrmFactice(avancement, statut)
    monkeypatch.setattr(api, "crm", c)
    return c


def test_api_cloture_refusee_a_0_pourcent(base, monkeypatch):
    c = _crm(monkeypatch, 0)
    with pytest.raises(HTTPException) as e:
        api.cloturer_ticket(7, base, "resp@arato.mg")
    assert e.value.status_code == 409 and not c.fermes


def test_api_cloture_refusee_si_critere_non_coche_puis_acceptee(base, monkeypatch):
    c = _crm(monkeypatch, 100)
    with pytest.raises(HTTPException) as e:
        api.cloturer_ticket(7, base, "resp@arato.mg")
    assert e.value.status_code == 409 and "critères" in e.value.detail and not c.fermes
    api.valider_critere(7, 0, api.ValidationCritereIn(valide=True), base, "resp@arato.mg")
    with pytest.raises(HTTPException):                                  # un seul critère coché sur deux
        api.cloturer_ticket(7, base, "resp@arato.mg")
    r = api.valider_critere(7, 1, api.ValidationCritereIn(valide=True), base, "resp@arato.mg")
    assert r["criteres_valides"] == [True, True] and r["cloturable"] is True
    assert api.cloturer_ticket(7, base, "resp@arato.mg") == {"ok": True} and c.fermes == [7]


def test_api_decocher_retire_la_possibilite_de_cloturer(base, monkeypatch):
    _crm(monkeypatch, 100)
    for i in (0, 1):
        api.valider_critere(7, i, api.ValidationCritereIn(valide=True), base, "r")
    r = api.valider_critere(7, 0, api.ValidationCritereIn(valide=False), base, "r")
    assert r["cloturable"] is False and r["criteres_valides"] == [False, True]


def test_api_critere_inexistant_404(base, monkeypatch):
    _crm(monkeypatch, 100)
    with pytest.raises(HTTPException) as e:
        api.valider_critere(7, 9, api.ValidationCritereIn(valide=True), base, "r")
    assert e.value.status_code == 404


def test_ticket_ancien_sans_critere_recoit_des_criteres_par_defaut(base, monkeypatch):
    c = _crm(monkeypatch, 100)
    c.t["criteres_acceptation"] = []
    r = api.criteres_du_ticket(7, base)
    assert 1 <= len(r["criteres_acceptation"]) <= 3 and r["criteres_par_defaut"] and r["cloturable"] is False


# ---------- chat ----------
TICKETS = {1: {"id": 1, "titre": "Recette API commandes", "description": "", "statut": "en_cours", "avancement_declare": 100,
               "membre_ids": [2], "depend_de_ids": [], "echeance": "2026-11-05", "criteres_acceptation": ["A fait.", "B fait."]},
           2: {"id": 2, "titre": "Export PDF", "description": "", "statut": "en_cours", "avancement_declare": 50,
               "membre_ids": [3], "depend_de_ids": [1], "echeance": "2026-11-09", "criteres_acceptation": ["C fait."]}}
TRACK = {i: {"situation": "normale", "libelle": "Échéance dans 3 jours", "avancement": t["avancement_declare"], "jours_retard": 0, "statut": t["statut"],
             "cloture_a_valider": t["avancement_declare"] >= 100} for i, t in TICKETS.items()}
NOMS = {2: "Miora Andry", 3: "Tojo Rabe"}


def _ctx(coches=()):
    etats = {i: T.etat_criteres(t["criteres_acceptation"], None, t["titre"], "", "", set(coches) if i == 1 else set(), t["statut"], t["avancement_declare"])
             for i, t in TICKETS.items()}
    return {"noms": NOMS, "etats": etats}


def _chat(q, ctx=None, monkeypatch=None):
    return agent.chat_conseil("P", q, TICKETS, TRACK, ctx or _ctx())["reponse"]


def test_chat_critere_par_titre_sans_numero():
    r = _chat("Quels sont les critères d'acceptation de la recette API ?")
    assert "[ ] A fait." in r and "Clôture impossible" in r and "cochés" in r


def test_chat_cloture_possible_quand_tout_est_coche():
    r = _chat("Quelles tâches peut-on clôturer ?", _ctx({"A fait.", "B fait."}))
    assert "Prêtes à clôturer" in r and "T-001" in r


def test_chat_cloture_a_100_mais_criteres_manquants():
    r = _chat("Quelles tâches peut-on clôturer ?")
    assert "critères à cocher" in r and "T-001" in r


def test_chat_taches_d_un_membre():
    r = _chat("Que fait Tojo ?")
    assert "T-002" in r and "T-001" not in r


def test_chat_question_sur_critere_n_est_plus_hors_champ():
    assert agent.chat_hors_sujet("P", "Les critères sont-ils tous validés pour la recette ?", TICKETS) is None
    assert agent.chat_hors_sujet("P", "Quelle est la météo demain à Paris ?", TICKETS) is not None
    # sans modèle (mode strict), une question sans lien avec le projet est écartée ; avec le modèle, c'est lui qui juge
    assert agent.chat_hors_sujet("P", "Parle-moi des volcans islandais", TICKETS, strict=True) is not None
    assert agent.chat_hors_sujet("P", "Parle-moi des volcans islandais", TICKETS) is None
    assert "agent IA de suivi" in agent.chat_hors_sujet("P", "Bonjour, qui es-tu ?", TICKETS)["reponse"]


def test_chat_outils_exposent_criteres_et_membres(monkeypatch):
    """Le modèle (factice) appelle criteres_ticket puis chercher_ticket : les outils renvoient des données exactes."""
    appels = []

    def faux(messages, tools=None, **k):
        n = len(appels)
        appels.append(1)
        if n == 0:
            return {"content": "", "tool_calls": [{"id": "a", "function": {"name": "criteres_ticket", "arguments": '{"ticket_id": 1}'}},
                                                  {"id": "b", "function": {"name": "chercher_ticket", "arguments": '{"texte": "export pdf"}'}},
                                                  {"id": "c", "function": {"name": "taches_du_membre", "arguments": '{"nom": "tojo"}'}}]}
        sorties = [m["content"] for m in messages if m["role"] == "tool"]
        assert '"cloturable": false' in sorties[0] and '"nb_criteres": 2' in sorties[0]
        assert "Export PDF" in sorties[1] and "Tojo Rabe" in sorties[1] and "Export PDF" in sorties[2]
        return {"content": "T-001 : 0 critère validé sur 2, clôture impossible."}
    monkeypatch.setattr(llm, "chat", faux)
    r = agent.chat_answer("P", "Où en sont les critères de la recette ?", TICKETS, TRACK, lambda i: [], None, _ctx())
    assert "T-001" in r["reponse"] and len(appels) == 2


# ---------- chat : tâches / projet déjà clôturés ----------
def _fermes(tous=True):
    tk = {i: {**t, "statut": "ferme", "avancement_declare": 100, "date_fermeture": "2026-10-30"} for i, t in TICKETS.items()}
    if not tous:
        tk[2] = TICKETS[2]
    tr = {i: {**TRACK[i], "situation": "ferme", "statut": "ferme"} for i in tk}
    return tk, tr


def test_chat_projet_deja_cloture_ne_repond_plus_aucune_tache_prete():
    tk, tr = _fermes()
    for q in ("Le projet est-il déjà clôturé ?", "Quelles tâches sont déjà fermées ?", "Est-ce que tout est terminé ?"):
        r = agent.chat_conseil("P", q, tk, tr, {"noms": NOMS, "etats": {}})["reponse"]
        assert "Le projet est terminé" in r and "T-001" in r and "Aucune tâche n'est prête" not in r, (q, r)


def test_chat_cloture_partielle_mentionne_les_fermees():
    tk, tr = _fermes(tous=False)
    r = agent.chat_conseil("P", "Quelles tâches peut-on clôturer ?", tk, tr, {"noms": NOMS, "etats": {}})["reponse"]
    assert "Tâches fermées" in r and "T-001" in r


def test_chat_libelle_de_repli_selon_la_cause():
    a = agent.chat_conseil("P", "Quel est l'état du projet ?", TICKETS, TRACK, _ctx(), hors_ligne=True)["reponse"]
    b = agent.chat_conseil("P", "Quel est l'état du projet ?", TICKETS, TRACK, _ctx(), hors_ligne="verif")["reponse"]
    assert "momentanément indisponible" in a and "n'a pas pu être vérifiée" in b and "momentanément indisponible" not in b


# ---------- chat : la réponse correspond à la question ----------
def _tickets_attente():
    tk = {**TICKETS, 2: {**TICKETS[2], "statut": "en_attente", "motif_attente_courant": "Attente de validation client"}}
    tr = {**TRACK, 2: {**TRACK[2], "statut": "en_attente"}}
    return tk, tr


def test_chat_y_a_t_il_une_tache_en_attente():
    tk, tr = _tickets_attente()
    r = agent.chat_conseil("P", "y a t il une tache en attente", tk, tr, {"noms": NOMS, "etats": {}})["reponse"]
    assert r.startswith("Oui, 1 tâche est en attente") and "T-002" in r and "Attente de validation client" in r
    assert "Mon avis" not in r and "Conseils" not in r                       # pas de rapport générique à côté de la question
    r2 = agent.chat_conseil("P", "Y a-t-il des tâches en attente ?", TICKETS, TRACK, {"noms": NOMS, "etats": {}})["reponse"]
    assert r2.startswith("Non, aucune tâche n'est en attente")


def test_chat_comptages_statuts_echeances_avancement():
    ctx = {"noms": NOMS, "etats": {}}
    assert "2 tâches" in agent.chat_conseil("P", "Combien de tâches y a-t-il ?", TICKETS, TRACK, ctx)["reponse"]
    assert "Prochaines échéances" in agent.chat_conseil("P", "Quelle est la prochaine échéance ?", TICKETS, TRACK, ctx)["reponse"]
    assert "Avancement déclaré" in agent.chat_conseil("P", "Quel est l'avancement des tâches ?", TICKETS, TRACK, ctx)["reponse"]
    assert agent.chat_conseil("P", "Des tâches sont-elles en cours ?", TICKETS, TRACK, ctx)["reponse"].startswith("Oui, 2 tâches")


def test_chat_question_non_comprise_ne_plaque_pas_un_rapport():
    r = agent.chat_conseil("P", "Les gens sont-ils contents du portail ?", TICKETS, TRACK, {"noms": NOMS, "etats": {}})["reponse"]
    assert "Constat" not in r and "Mon avis" not in r


# ---------- tâches répétitives ----------
def _t(i, titre, desc="", src="", dep=(), duree=2):
    return {"id": i, "titre": titre, "description": desc, "source_dans_document": src, "depend_de": list(dep),
            "duree_estimee_jours": duree, "ambiguites": []}


def test_fusion_des_taches_repetitives_et_dependances_redirigees():
    taches = [_t(1, "Gestion des utilisateurs", "Créer, modifier et supprimer les comptes utilisateurs", "L'administrateur gère les comptes utilisateurs de la plateforme."),
              _t(2, "Export des factures", "Export PDF des factures", "Le client exporte ses factures au format PDF depuis son espace."),
              _t(3, "Gestion des comptes utilisateurs", "Créer, modifier et supprimer les comptes des utilisateurs", "Les comptes utilisateurs sont gérés par l'administrateur.", duree=5),
              _t(4, "Envoi d'e-mails", "E-mail de confirmation", "Un e-mail de confirmation est envoyé après chaque paiement.", dep=[3]),
              _t(5, "Export des factures PDF", "Export PDF des factures du client", "Le client exporte ses factures au format PDF depuis son espace.")]
    res, fus = T.dedoublonner_taches(taches)
    assert [t["id"] for t in res] == [1, 2, 4] and len(fus) == 2
    assert res[0]["duree_estimee_jours"] == 5                       # la durée la plus longue est conservée
    assert next(t for t in res if t["id"] == 4)["depend_de"] == [1]   # la dépendance vers la tâche fusionnée pointe vers la tâche conservée


def test_taches_differentes_ne_sont_pas_fusionnees():
    a = _t(1, "Connexion du client", "Connexion par e-mail et mot de passe", "Le client se connecte par e-mail et mot de passe, session de 30 minutes.")
    b = _t(2, "Export des factures", "Export PDF des factures", "Le client exporte ses factures au format PDF depuis son espace.")
    c = _t(3, "Export des impayés", "Export CSV des factures impayées", "L'administrateur exporte les factures impayées au format CSV.")
    assert T.dedoublonner_taches([a, b, c])[0] == [a, b, c]


# ---------- chat : réponses ciblées sur une tâche ----------
def test_chat_reponses_ciblees_sur_une_tache():
    tk = {**TICKETS, 1: {**TICKETS[1], "description": "Recette des API de commandes avec le client."}}
    ctx = {"noms": NOMS, "etats": {}}
    q = lambda texte: agent.chat_conseil("P", texte, tk, TRACK, ctx)["reponse"]
    assert "Recette des API" in q("De quoi parle T-001 ?")
    assert "Export PDF" in q("Quelles tâches dépendent de T-001 ?") or "retient" in q("Que bloque T-001 ?")
    assert "Miora Andry" in q("Qui est responsable de T-001 ?") and "Statut" not in q("Qui est responsable de T-001 ?")
    assert "2026-11-05" in q("Quelle est l'échéance de T-001 ?")
    assert "T-002" in q("Liste de toutes les tâches du projet")
