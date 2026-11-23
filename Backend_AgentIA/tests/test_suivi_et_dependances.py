"""Contrôles : dépendances entre tâches (aucun cycle), synthèse sans tâche oubliée (bug T-039), e-mails (SMTP réel local).
Lancer : cd Backend_AgentIA && python -m pytest tests -q"""
import smtplib
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import agent, mailer, tools as T          # noqa: E402


def tk(i, titre, deps=None):
    return {"id": i, "titre": titre, "depend_de": list(deps or [])}


# ---------- Dépendances ----------
def test_dependances_par_phases_suivent_l_ordre_naturel_d_un_projet():
    taches = [tk(1, "Analyse des besoins"), tk(2, "Conception de la base"), tk(3, "Développement de l'API"),
              tk(4, "Tests et recette"), tk(5, "Déploiement en production"), tk(6, "Charte graphique")]
    agent._ajouter_sans_cycle(taches, agent._dependances_par_phases(taches))
    assert [t["depend_de"] for t in taches] == [[], [1], [2], [3], [4], []]      # la tâche sans phase reste indépendante
    assert T.check_dependencies(taches)["ok"]


def test_une_dependance_qui_cree_un_cycle_est_refusee():
    taches = [tk(1, "a"), tk(2, "b", [1]), tk(3, "c", [2])]
    assert agent._ajouter_sans_cycle(taches, [(1, 3), (2, 2), (9, 1), (3, 99)]) == 0
    assert taches[0]["depend_de"] == [] and T.check_dependencies(taches)["ok"]


def test_cartographie_sans_ia_utilise_le_repli_et_ne_leve_pas(monkeypatch):
    def hors_ligne(*a, **k):
        raise RuntimeError("hors ligne")
    monkeypatch.setattr(agent.llm, "chat", hors_ligne)
    taches = [tk(1, "Conception"), tk(2, "Développement"), tk(3, "Tests")]
    assert agent.cartographier_dependances(taches) == 2
    assert [t["depend_de"] for t in taches] == [[], [1], [2]]


# ---------- Synthèse : aucune tâche ajoutée n'est oubliée ----------
FAITS = {"projet": "P", "en_retard": [], "a_surveiller": [], "en_attente": [], "priorites": [], "risques": [],
         "evolutions": ["T-001 : le statut est passé de « Nouveau » à « Ouvert ».", "T-002 : x.", "T-003 : y.", "T-004 : z.",
                        "T-039, T-040 et T-041 ont été ajoutées au projet : « a », « b », « c »."]}


def test_synthese_deterministe_cite_toutes_les_taches_ajoutees():
    txt = agent.synthese_deterministe(FAITS)
    assert all(f"T-0{n}" in txt for n in (39, 40, 41))


def test_synthese_llm_qui_oublie_une_tache_est_rejetee(monkeypatch):
    monkeypatch.setattr(agent.llm, "chat", lambda *a, **k: {"content": "T-040 et T-041 ont été ajoutées au projet."})
    txt, source = agent.synthese_narrative(FAITS)
    assert source == "fallback" and "T-039" in txt


# ---------- E-mails : un vrai dialogue SMTP local ----------
class _Smtp(socketserver.StreamRequestHandler):
    recus: list = []

    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())
        w("220 test ESMTP")
        data, en_data = [], False
        for brut in self.rfile:
            ligne = brut.decode(errors="replace").rstrip("\r\n")
            if en_data:
                if ligne == ".":
                    en_data = False
                    type(self).recus.append("\n".join(data))
                    data = []
                    w("250 ok")
                else:
                    data.append(ligne)
                continue
            cmd = ligne.upper()
            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                w("250 test")
            elif cmd.startswith(("MAIL", "RCPT")):
                w("250 ok")
            elif cmd == "DATA":
                en_data = True
                w("354 go")
            elif cmd == "QUIT":
                w("221 bye")
                return
            else:
                w("250 ok")


def test_lot_d_emails_sur_une_seule_connexion():
    _Smtp.recus = []
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Smtp) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cfg = {"server": "127.0.0.1", "port": srv.server_address[1]}
        res = mailer.send_batch([("a@arato.mg", "Bonjour A", "S1"), ("pas-une-adresse", "x", "S2"), ("b@arato.mg", "Bonjour B", "S3")], cfg)
        srv.shutdown()
    assert [r[0] for r in res] == ["envoye", "echec", "envoye"]
    assert len(_Smtp.recus) == 2


def test_serveur_injoignable_est_archive_et_une_erreur_d_auth_n_est_pas_prise_pour_un_serveur_injoignable():
    res = mailer.send_batch([("a@arato.mg", "x", "s")], {"server": "127.0.0.1", "port": 1})
    assert res[0][0] == "archive"
    assert not mailer._injoignable(smtplib.SMTPAuthenticationError(535, b"refus"))   # SMTPException hérite d'OSError : piège évité
    assert mailer._injoignable(ConnectionRefusedError())
