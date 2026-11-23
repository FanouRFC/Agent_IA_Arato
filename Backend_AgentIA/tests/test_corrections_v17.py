"""Corrections v17 : nom de projet unique, synthèse exacte et concise, échéance prise en compte, rapports et e-mails robustes.
Lancer : cd Backend_AgentIA && python -m pytest tests -q"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import agent, mailer, projects, reports, service      # noqa: E402


def test_nom_de_projet_compare_sans_casse_ni_accent_ni_espaces():
    assert projects.cle_nom("  Ézaka  ") == projects.cle_nom("EZAKA") == projects.cle_nom("ezaka")
    assert projects.cle_nom("Migration   ERP") == projects.cle_nom("migration erp")
    assert projects.nom_propre("  Mon   projet ") == "Mon projet"


def faits(**k):
    base = {"projet": "EZAKA", "total": 2, "en_retard": [], "a_surveiller": [], "en_attente": [], "termine": [],
            "priorites": [], "risques": [], "evolutions": []}
    return {**base, **k}


def test_synthese_compte_chaque_tache_une_seule_fois():
    t = agent.synthese_deterministe(faits(a_surveiller=[{"id": 89}], termine=[88],
                                          priorites=[{"id": 89, "raisons": ["échéance dans 1 jour, avancement déclaré 0 %"]}]))
    assert "1 tâche à surveiller, 1 terminée" in t and "en attente" not in t
    assert "T-089 (échéance dans 1 jour)" in t


def test_synthese_est_courte():
    t = agent.synthese_deterministe(faits(total=8, en_retard=[{"id": 26}, {"id": 6}, {"id": 19}], en_attente=[{"id": 1}, {"id": 2}],
                                          priorites=[{"id": 26, "raisons": ["retard de 7 jours", "aucun motif documenté"]}, {"id": 6, "raisons": []}]))
    assert t.startswith("Projet « EZAKA » : 3 tâches en retard, 2 en attente.") and len(t.split()) < 30 and "Risque" not in t


def test_ecarts_detecte_une_echeance_decalee():
    tk = {1: {"statut": "ouvert", "avancement_declare": 0}}
    tr = {1: {"situation": "normale", "jours_retard": 0, "avancement": 0, "echeance": "2026-11-20", "jours_restants": 9}}
    ancien = {"v": service.FORMAT_SYNTHESE, "par_ticket": {"1": {"situation": "a_surveiller", "jours_retard": 0, "avancement": 0, "statut": "ouvert",
                                                                    "echeance": "2026-11-12", "jours_restants": 1, "motif": ""}}}
    ids, nature = service.ecarts(ancien, tk, tr)
    assert ids == {1} and nature == "modification de l'échéance"
    assert service.ecarts({**ancien, "par_ticket": {"1": {**ancien["par_ticket"]["1"], **{"situation": "normale", "echeance": "2026-11-20", "jours_restants": 9}}}}, tk, tr)[1] == ""


def test_rapport_excel_accepte_caracteres_de_controle_et_formules():
    from openpyxl import load_workbook
    tk = {1: {"titre": "=SUM(A1)\x0b titre\x0c", "statut": "ouvert", "avancement_declare": 0, "membre_ids": []}}
    tr = {1: {"situation": "normale", "libelle": "ok"}}
    stats = {"total": 1, "par_statut": {k: 0 for k in ("nouveau", "ouvert", "en_cours", "en_attente", "ferme")}, "en_retard": 0, "a_surveiller": 0}
    wb = load_workbook(io.BytesIO(reports.xlsx(projet="=P\x01", synthese="a\x0bb", tickets=tk, tracking=tr, stats=stats, recos=[])))
    assert wb["Tickets"]["B2"].value == "=SUM(A1) titre" and wb["Tickets"]["B2"].data_type == "s"
    assert reports.pdf(projet="x\x0b", synthese="a\x0cb", tickets=tk, tracking=tr, stats=stats, recos=[]).startswith(b"%PDF")


def test_pdf_de_secours_si_la_mise_en_page_complete_echoue(monkeypatch):
    monkeypatch.setattr(reports, "_build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    stats = {"total": 0, "par_statut": {k: 0 for k in ("nouveau", "ouvert", "en_cours", "en_attente", "ferme")}, "en_retard": 0, "a_surveiller": 0}
    assert reports.pdf(projet="P", synthese="s", tickets={}, tracking={}, stats=stats, recos=[]).startswith(b"%PDF")


def test_message_d_echeance_en_francais_et_sans_reference_a_la_configuration():
    assert "28/10/2026" in mailer.affectation_text("A", "T", 5, "2026-10-28")
    import smtplib
    assert "MAIL_" not in mailer._expliquer(smtplib.SMTPAuthenticationError(535, b"x"), {"sender": "a@b.c"})
