"""Scénarios bout en bout contre la pile EN FONCTIONNEMENT (backend :8000, CRM :8001, PostgreSQL). Non collecté par pytest.
Lancer : python tests/e2e_live.py   (jeu de données : python -m app.seed dans CRM_AgentIA ; ./lancer_*.bat)"""
import datetime as dt, sys, time, httpx
B, C = "http://127.0.0.1:8000", "http://127.0.0.1:8001"
b, crm = httpx.Client(base_url=B, timeout=120), httpx.Client(base_url=C, timeout=30)
res = []
def check(nom, cond, detail=""):
    res.append(cond); print(("OK  " if cond else "ECHEC"), nom, detail)
def attendre(fn, s=20):
    t0 = time.time()
    while time.time() - t0 < s:
        v = fn()
        if v: return v
        time.sleep(1)
    return None

r = b.post("/auth/login", json={"email": "responsable@arato.mg", "mot_de_passe": "changeme"})
check("1 connexion responsable", r.status_code == 200); h = {"Authorization": "Bearer " + r.json()["token"]}
check("1b route protégée sans jeton", b.get("/projets").status_code == 401)
for i in range(6): x = b.post("/auth/login", json={"email": "x@y.zz", "mot_de_passe": "faux"})
check("1c blocage après échecs répétés (429)", x.status_code == 429)

pid = next(p["id"] for p in b.get("/projets", headers=h).json() if p["nom"] == "Agent IA Arato")
tk = {t["id"]: t for t in crm.get("/tickets").json()}
proj_crm = max(t["projet_id"] for t in tk.values())
mine = [t for t in tk.values() if t["projet_id"] == proj_crm]
check("3-6 tickets créés dans le CRM avec critères", len(mine) == 23 and all(t["criteres_acceptation"] for t in mine), f"{len(mine)} tickets")
T = mine[0]; tid = T["id"]; m = T["membre_ids"][0]
d = b.get(f"/tickets/{tid}/analyse", headers=h).json()
check("4 critères dans le détail du ticket (API)", len(d["criteres_acceptation"]) >= 1)
check("4b endpoint dédié /criteres", b.get(f"/tickets/{tid}/criteres", headers=h).json()["criteres_acceptation"] == d["criteres_acceptation"])

# P1 : 100 % sans fermeture
for st in ("en_cours",):
    crm.put(f"/tickets/{tid}/statut", json={"statut": st, "auteur_id": m})
for v in (25, 100): crm.put(f"/tickets/{tid}/avancement", json={"avancement": v, "auteur_id": m})
t = crm.get(f"/tickets/{tid}").json()
check("7-8 avancement 100 % : statut inchangé", t["avancement_declare"] == 100 and t["statut"] == "en_cours" and t["date_fermeture"] is None)
dash = attendre(lambda: next((r for r in b.get(f"/projets/{pid}/dashboard", headers=h).json()["tickets"] if r["id"] == tid and r["cloture_a_valider"]), None))
check("8b tableau de bord : « clôture à valider »", bool(dash))
reco = attendre(lambda: [x for x in b.get(f"/projets/{pid}/synthese", headers=h).json()["recommandations"] if x["id_ticket"] == tid])
check("8c recommandation « valider la clôture »", bool(reco) and "clôture" in reco[0]["texte"], reco[0]["texte"][:90] if reco else "")
check("8d CRM refuse la fermeture par un membre", crm.put(f"/tickets/{tid}/statut", json={"statut": "ferme", "auteur_id": m}).status_code == 409)
check("8e CRM refuse la clôture sans clé", crm.put(f"/tickets/{tid}/cloture", json={"valide_par": "a@b.c"}).status_code == 403)
mails = lambda: sum("E-mail" in j["action"] for j in b.get("/admin/journal", headers=h).json())
nb_mails = mails()
r = b.post(f"/tickets/{tid}/cloture", headers=h)
check("8f clôture validée par le responsable", r.status_code == 200 and crm.get(f"/tickets/{tid}").json()["statut"] == "ferme")
check("8g clôture inscrite au journal", any("Clôture de" in j["action"] for j in b.get("/admin/journal", headers=h).json()))
check("8h double clôture refusée", b.post(f"/tickets/{tid}/cloture", headers=h).status_code == 409)

# P3 : suivi temporel : un ticket créé par l'équipe avec échéance passée est détecté sans action humaine
hier = str(dt.date.today() - dt.timedelta(days=4))
n = crm.post("/equipe/tickets", json={"titre": "Test retard auto", "projet_id": proj_crm, "echeance": hier, "membre_ids": [m]}).json()
t0 = time.time()
ok = attendre(lambda: crm.get(f"/tickets/{n['id']}").json()["est_en_retard"], 30)
check("9 est_en_retard écrit par le scheduler", bool(ok), f"en {time.time()-t0:.1f} s")
calc = b.get(f"/tickets/{n['id']}/analyse", headers=h).json()["calculs"]
check("9b jours de retard ouvrés exacts", calc["jours_retard"] >= 2 and calc["est_en_retard"], f"{calc['jours_retard']} j · {calc['libelle']}")
echeance_avant = crm.get(f"/tickets/{n['id']}").json()["echeance"]; time.sleep(6)
check("9c aucune replanification automatique", crm.get(f"/tickets/{n['id']}").json()["echeance"] == echeance_avant)
check("10 aucune relance ni e-mail automatique après clôture/retard", mails() == nb_mails, f"{nb_mails} e-mails au journal, inchangé")

# 11 synthèse, 12 chat, 13 LLM
s = b.get(f"/projets/{pid}/synthese", headers=h).json()
check("11 synthèse dynamique produite", bool(s["synthese"] and s["synthese"]["contenu"]), s["synthese"]["contenu"][:70] if s["synthese"] else "")
c = b.post(f"/projets/{pid}/chat", headers=h, json={"question": "Quelles tâches sont en retard ?"})
check("12 chat interactif répond", c.status_code == 200 and len(c.json()["reponse"]) > 10, c.json()["reponse"][:70])
l = b.post("/admin/llm/test", headers=h).json()
check("13 test Ollama (serveur→modèle→génération)", l.get("ok") and len(l["etapes"]) == 3, str(l.get("latence_ms")) + " ms")
check("13b modèles listés", "llama3.1:8b" in b.get("/admin/llm/modeles", headers=h).json()["modeles"])
print(f"\n{sum(res)}/{len(res)} vérifications réussies"); sys.exit(0 if all(res) else 1)
