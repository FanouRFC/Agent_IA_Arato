"""Rapports PDF et Excel : génération robuste (caractères spéciaux), contenu et en-tête Arato.
Lancer : cd Backend_AgentIA && python -m pytest tests -q"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import reports          # noqa: E402

TK = {1: {"titre": "Conception & maquettes <v2>", "statut": "en_cours", "avancement_declare": 40, "membre_ids": [1],
          "motif_retard_courant": "Dépendance > externe & retard"},
      2: {"titre": "Tests", "statut": "ferme", "avancement_declare": 100, "membre_ids": []}}
TR = {1: {"situation": "en_retard", "libelle": "2 jours de retard"}, 2: {"situation": "ferme", "libelle": "Fermé"}}
STATS = {"total": 2, "par_statut": {"nouveau": 0, "ouvert": 0, "en_cours": 1, "en_attente": 0, "ferme": 1}, "en_retard": 1, "a_surveiller": 0}
EC = {"niveau": "tendu", "titre": "Projet sous tension", "phrase": "1 tâche sur 2 est en retard.", "progression": 70, "prochaine": None}
ARGS = dict(projet="Refonte & site <web>", synthese="Ligne 1.\nLigne avec < et & et </b>.", tickets=TK, tracking=TR, stats=STATS,
            recos=[("T-001 : contacter l'équipe & vérifier <x>", "suivie"), ("T-002 : relancer", None)], en_clair=EC, noms={1: "Anna"},
            priorites=[{"id": 1, "rang": 1, "titre": "Conception", "raisons": ["en retard"]}],
            risques=[{"id": 1, "risque": "eleve", "titre": "Conception", "prediction": "Le retard va se prolonger."}],
            evolutions=[{"t": "2026-10-21T10:15:00", "txt": "T-039, T-040 et T-041 ont été ajoutées au projet."}])


def test_pdf_se_genere_avec_des_caracteres_speciaux():
    b = reports.pdf(**ARGS)
    assert b.startswith(b"%PDF") and len(b) > 5000


def test_pdf_sans_donnees_optionnelles():
    b = reports.pdf(projet="Vide", synthese="", tickets={}, tracking={}, stats={**STATS, "total": 0, "en_retard": 0}, recos=[])
    assert b.startswith(b"%PDF")


def test_excel_contient_les_feuilles_attendues():
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(reports.xlsx(**ARGS)))
    assert {"Synthèse", "Tickets", "Priorités et risques", "Évolution", "Recommandations"} <= set(wb.sheetnames)
