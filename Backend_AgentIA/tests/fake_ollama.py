"""Serveur local qui imite l'API d'Ollama (compatible OpenAI) : /v1/models, /api/tags, /v1/chat/completions.

ATTENTION : ce n'est PAS un modèle de langage. Il sert à exercer, par de vrais appels HTTP, le client `llm.py` et l'agent
(création de tâches, critères d'acceptation, chat) quand Ollama n'est pas installé (poste de test, CI, sandbox sans accès au registre).
Ses réponses sont produites par des règles simples à partir du texte reçu : elles ne prouvent rien sur la qualité d'un vrai modèle.

Utilisation : python -m tests.fake_ollama [port]   (défaut 11434)  ou, en test, `with FakeOllama() as srv:` (port libre).
Options : tools_supported=False simule un modèle sans appel d'outils (HTTP 400 « does not support tools » comme Ollama)."""
import json
import os
import re
import time
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELES = ["llama3.1:8b", "qwen2.5:7b-instruct"]


def _phrases(texte: str, mini=45, maxi=220) -> list[str]:
    lignes = [re.sub(r"^[\s•\-\*·▪●\d.)]+", "", l).strip() for l in texte.splitlines()]
    return [l for l in lignes if mini <= len(l) <= maxi and l[0].isalpha() and not l.lower().startswith("cahier des charges")]


def _taches(user: str) -> dict:
    doc = user.split("Cahier des charges :", 1)[-1]
    taches = []
    for i, ph in enumerate(_phrases(doc)[:4], 1):
        titre = " ".join(ph.split()[:7]).rstrip(",;:.")
        taches.append({"id": i, "titre": titre[:1].upper() + titre[1:], "description": ph, "priorite": ["haute", "moyenne", "basse"][i % 3],
                       "raison_priorite": "exigence du document", "duree_estimee_jours": 2 + i, "depend_de": [],
                       "source_dans_document": ph, "niveau_confiance": 0.8, "profil_recommande": "Développeur backend",
                       "nb_membres_recommande": 1, "membre_ids_proposes": [], "ambiguites": []})
    return {"taches": taches, "ambiguites_globales": []}


def _criteres(user: str) -> dict:
    out = []
    for t in json.loads(user)["taches"]:
        base = [t.get("extrait") or ""]
        crit = []
        for ph in base:
            ph = ph.strip().rstrip(".;:")
            if len(ph) >= 30 and ph not in crit:
                crit.append(ph)
        def phrase(c: str) -> str:
            premier = c.split()[0].lower()
            if re.search(r"(er|ir|re)$", premier) and len(premier) > 4:
                return f"Le logiciel permet de {c[0].lower() + c[1:]}."
            return f"Le livrable respecte l'exigence : {c[0].lower() + c[1:]}."
        out.append({"id": t["id"], "criteres_acceptation": [phrase(c) for c in crit[:3]]})
    return {"criteres": out}


class FakeOllama:
    def __init__(self, port=0, tools_supported=True, modeles=None, reponse_chat="Réponse de test."):
        self.tools_supported, self.modeles, self.reponse_chat = tools_supported, modeles or MODELES, reponse_chat
        self.requetes: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, corps):
                b = json.dumps(corps).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/v1/models":
                    self._json(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "library"} for m in outer.modeles]})
                elif self.path == "/api/tags":
                    self._json(200, {"models": [{"name": m, "model": m} for m in outer.modeles]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.requetes.append(corps)
                time.sleep(float(os.environ.get("FAKE_OLLAMA_DELAY", "0")))   # simule un modèle lent (tests d'interface)
                if self.path != "/v1/chat/completions":
                    return self._json(404, {"error": "not found"})
                if corps.get("model") not in outer.modeles:
                    return self._json(404, {"error": {"message": f"model '{corps.get('model')}' not found", "type": "api_error"}})
                if corps.get("tools") and not outer.tools_supported:
                    return self._json(400, {"error": {"message": f"registry.ollama.ai/library/{corps['model']} does not support tools"}})
                msgs = corps["messages"]
                systeme, user = msgs[0]["content"], msgs[-1]["content"]
                if "critères d'acceptation" in systeme and "Réponds par UN SEUL objet JSON" in systeme and user.startswith("{"):
                    contenu = json.dumps(_criteres(user), ensure_ascii=False)
                elif "Extrais du cahier des charges" in systeme:
                    contenu = json.dumps(_taches(user), ensure_ascii=False)
                elif "dépendances logiques" in systeme:
                    contenu = json.dumps({"dependances": []})
                elif "Réponds uniquement : OK" in user:
                    contenu = "OK"
                else:
                    contenu = outer.reponse_chat
                self._json(200, {"id": "x", "object": "chat.completion", "model": corps["model"],
                                 "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": contenu}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    srv = FakeOllama(int(sys.argv[1]) if len(sys.argv) > 1 else 11434)
    print("Faux Ollama (simulateur, pas un modèle) sur", srv.url)
    srv.httpd.serve_forever()
