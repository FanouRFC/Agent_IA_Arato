"""Contrôles des calculs déterministes (jours ouvrés, retards, échéances) et de l'affectation multi-membres.
Lancer : cd Backend_AgentIA && python -m pytest tests -q"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import affectation, tools as T          # noqa: E402
from app.calendar_utils import add_bd, bd_between  # noqa: E402

D = dt.date
FERIES = frozenset({D(2026, 11, 3)})              # mardi


def tk(statut="en_cours", ech="2026-10-12", av=0, fin=None):
    return {"id": 1, "statut": statut, "avancement_declare": av, "echeance": ech, "date_fermeture": fin}


def calc(t, now, **kw):
    return T.compute_tracking(t, now, kw.pop("hol", frozenset()), **kw)


def test_add_bd_saute_week_end_et_feries():
    assert add_bd(D(2026, 10, 16), 1) == D(2026, 10, 19)          # vendredi + 1 = lundi
    assert add_bd(D(2026, 10, 17), 1) == D(2026, 10, 19)          # samedi + 1 = lundi
    assert add_bd(D(2026, 10, 30), 3, FERIES) == D(2026, 11, 5)   # ven + 3 j : lun 2, (mar 3 férié), mer 4, jeu 5
    assert add_bd(D(2026, 10, 19), 0) == D(2026, 10, 19)


def test_bd_between_intervalle_ouvert_a_gauche():
    assert bd_between(D(2026, 10, 12), D(2026, 10, 15)) == 3      # exemple du cahier : lundi 12 → jeudi 15 = 3 jours
    assert bd_between(D(2026, 10, 16), D(2026, 10, 19)) == 1      # vendredi → lundi
    assert bd_between(D(2026, 10, 15), D(2026, 10, 15)) == 0


def test_retard_exemple_du_cahier():
    r = calc(tk(ech="2026-10-12"), dt.datetime(2026, 10, 15, 10, 0))
    assert r["est_en_retard"] and r["jours_retard"] == 3 and r["situation"] == "en_retard"


def test_pas_de_retard_le_jour_de_l_echeance_avant_17h():
    r = calc(tk(ech="2026-10-15"), dt.datetime(2026, 10, 15, 16, 59))
    assert not r["est_en_retard"]
    r = calc(tk(ech="2026-10-15"), dt.datetime(2026, 10, 15, 17, 1))
    assert r["est_en_retard"] and r["jours_retard"] == 0


def test_echeance_un_samedi_consultee_le_dimanche():
    r = calc(tk(ech="2026-10-17"), dt.datetime(2026, 10, 18, 9, 0))
    assert r["est_en_retard"] and r["jours_retard"] == 0 and "aujourd'hui" not in r["libelle"]


def test_en_attente_en_retard_reste_compte_en_retard():
    r = calc(tk(statut="en_attente", ech="2026-10-12"), dt.datetime(2026, 10, 14, 9, 0))
    assert r["situation"] == "en_retard" and r["jours_retard"] == 2


def test_a_surveiller_seuils_inclusifs():
    now = dt.datetime(2026, 10, 14, 9, 0)
    assert calc(tk(ech="2026-10-16", av=50), now)["situation"] == "a_surveiller"   # 2 jours, 50 %
    assert calc(tk(ech="2026-10-16", av=51), now)["situation"] == "normale"
    assert calc(tk(ech="2026-10-19", av=0), now)["situation"] == "normale"        # 3 jours restants


def test_ticket_ferme_conserve_son_retard_final():
    r = calc(tk(statut="ferme", ech="2026-10-12", av=100, fin="2026-10-15"), dt.datetime(2026, 10, 20))
    assert r["situation"] == "ferme" and r["retard_final"] == 3 and not r["est_en_retard"]
    r = calc(tk(statut="ferme", ech="2026-10-12", av=100, fin="2026-10-12"), dt.datetime(2026, 10, 20))
    assert r["retard_final"] == 0


def test_jours_feries_exclus_du_retard():
    r = calc(tk(ech="2026-10-30"), dt.datetime(2026, 11, 4, 9, 0), hol=FERIES)   # ven 30 → mer 4 : lun 2, mer 4 (mar 3 férié)
    assert r["jours_retard"] == 2


# ---------------- affectation multi-membres ----------------
MEMBRES = [{"id": i, "profil": p} for i, p in enumerate(
    ["Développeur backend", "Développeur frontend", "Designer UI/UX", "Testeur QA", "Chef de projet"], 1)]


def test_affectation_plusieurs_membres_selon_nb_recommande():
    ts = [{"id": 1, "profil_recommande": "développeur", "nb_membres_recommande": 3, "duree_estimee_jours": 2},
          {"id": 2, "profil_recommande": "testeur", "nb_membres_recommande": 1, "duree_estimee_jours": 2}]
    affectation.affecter(ts, MEMBRES, [])
    assert len(ts[0]["membre_ids_proposes"]) == 3 and len(set(ts[0]["membre_ids_proposes"])) == 3
    assert {1, 2} <= set(ts[0]["membre_ids_proposes"])           # profils « développeur » d'abord
    assert ts[1]["membre_ids_proposes"] == [4]


def test_affectation_defaut_selon_duree_et_jamais_sans_membre():
    ts = [{"id": 1, "duree_estimee_jours": 8}, {"id": 2, "duree_estimee_jours": 1}]
    affectation.affecter(ts, MEMBRES, [])
    assert len(ts[0]["membre_ids_proposes"]) == 2 and len(ts[1]["membre_ids_proposes"]) == 1


def test_affectation_garde_les_propositions_valides_sans_doublon():
    ts = [{"id": 1, "membre_ids_proposes": [2, 2, 99], "nb_membres_recommande": 2, "duree_estimee_jours": 3}]
    affectation.affecter(ts, MEMBRES, [])
    assert ts[0]["membre_ids_proposes"][0] == 2 and len(ts[0]["membre_ids_proposes"]) == 2 and 99 not in ts[0]["membre_ids_proposes"]


def test_affectation_equilibre_la_charge_et_borne_au_nombre_de_membres():
    ts = [{"id": k, "nb_membres_recommande": 1, "duree_estimee_jours": 1} for k in range(5)]
    affectation.affecter(ts, MEMBRES, [])
    assert sorted(t["membre_ids_proposes"][0] for t in ts) == [1, 2, 3, 4, 5]    # 5 tâches, 5 personnes : chacun une
    deux = [{"id": 1, "nb_membres_recommande": 3, "duree_estimee_jours": 9}]
    affectation.affecter(deux, MEMBRES[:2], [])
    assert len(deux[0]["membre_ids_proposes"]) == 2                               # pas plus que de membres


# ---------- Vulgarisation « en clair » ----------
def _tk(statut, av, ech="2026-10-30"):
    return {"titre": "t", "statut": statut, "avancement_declare": av, "echeance": ech}


def test_en_clair_niveaux_et_progression():
    import datetime as dt
    from app import plain
    today = dt.date(2026, 10, 19)
    T = {1: _tk("en_cours", 50), 2: _tk("ferme", 100), 3: _tk("ouvert", 0)}
    sit = lambda s: {"situation": s, "echeance": "2026-10-30", "jours_restants": 8}
    r = plain.en_clair(T, {1: sit("normale"), 2: sit("ferme"), 3: sit("normale")}, frozenset(), today)
    assert r["niveau"] == "serein" and r["progression"] == 50 and r["fermees"] == 1
    r = plain.en_clair(T, {1: sit("en_retard"), 2: sit("ferme"), 3: sit("a_surveiller")}, frozenset(), today)
    assert r["niveau"] == "tendu" and r["chiffres"][1]["valeur"] == 1
    r = plain.en_clair({2: _tk("ferme", 100)}, {2: sit("ferme")}, frozenset(), today)
    assert r["niveau"] == "termine" and r["progression"] == 100
    assert plain.en_clair({}, {}, frozenset(), today)["niveau"] == "vide"


# ---------- Messagerie ----------
def test_mail_serveur_injoignable_est_archive_et_adresse_invalide_refusee(tmp_path, monkeypatch):
    import pytest
    from app import mailer
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path)
    cfg = {"server": "127.0.0.1", "port": 1, "sender": "a@b.mg"}          # port 1 : personne n'écoute
    statut, detail = mailer.send("x@arato.mg", "Bonjour", "Test", cfg)
    assert statut == "archive" and "injoignable" in detail
    assert len(list(tmp_path.glob("*.eml"))) == 1
    with pytest.raises(mailer.MailError):
        mailer.send("pas-une-adresse", "Bonjour", "Test", cfg)
    assert mailer.config_effective({"port": "2525"})["port"] == 2525
