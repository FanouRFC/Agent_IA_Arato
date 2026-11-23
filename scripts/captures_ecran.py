"""Captures d'écran réelles de l'application en fonctionnement (aucune maquette).
Prérequis : backend (8000), CRM (8001) et frontend (npm run dev, port 5173) lancés, puis :
    pip install playwright && playwright install chromium
    python scripts/captures_ecran.py responsable@arato.mg changeme
Les images sont enregistrées dans ./captures (1920x1080, définition x2, page seule : aucun terminal ni outil de développement)."""
import sys, pathlib
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"
email, mdp = (sys.argv + ["responsable@arato.mg", "changeme"])[1:3]
out = pathlib.Path("captures"); out.mkdir(exist_ok=True)

with sync_playwright() as p:
    nav = p.chromium.launch()
    page = nav.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2, locale="fr-FR").new_page()
    page.goto(f"{URL}/login"); page.fill("#email", email); page.fill("input[type=password]", mdp)
    page.click("button.btn-primary"); page.wait_for_url(f"{URL}/")
    page.goto(f"{URL}/projets"); page.wait_for_load_state("networkidle")
    page.locator("main button, main a").filter(has_text="Ouvrir").first.click()   # entre dans le premier projet
    page.wait_for_load_state("networkidle")
    page.goto(f"{URL}/tableau"); page.wait_for_selector(".nx-table tbody tr"); page.wait_for_timeout(1200)
    page.screenshot(path=out / "01_tableau_de_bord_haut.png")
    page.screenshot(path=out / "02_tableau_de_bord_complet.png", full_page=True)
    page.locator(".nx-table").scroll_into_view_if_needed(); page.screenshot(path=out / "03_tableau_des_tickets.png")
    page.goto(f"{URL}/situation"); page.wait_for_selector(".nx-chat"); page.wait_for_timeout(1200)
    page.screenshot(path=out / "04_synthese_et_chat.png")
    nav.close()
print("Captures enregistrées dans", out.resolve())
