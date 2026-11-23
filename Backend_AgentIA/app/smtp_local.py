"""Boîte d'envoi de TEST intégrée : quand MAIL_SERVER pointe sur localhost, ce petit serveur SMTP démarre avec le backend (aucun
programme à lancer à part). Il accepte les messages ; chacun reste lisible en .eml dans data/outbox. Rien n'est envoyé sur Internet :
pour de vraies boîtes de réception, il faut renseigner un compte d'envoi réel dans .env."""
import logging
import socket
import socketserver
import threading

log = logging.getLogger("smtp_local")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        def w(s: str):
            self.wfile.write((s + "\r\n").encode())
        w("220 arato-test ESMTP")
        en_data = False
        for brut in self.rfile:
            ligne = brut.rstrip(b"\r\n")
            if en_data:
                if ligne == b".":
                    en_data = False
                    w("250 ok")
                continue
            cmd = ligne.decode(errors="replace").upper()
            if cmd == "DATA":
                en_data = True
                w("354 go")
            elif cmd == "QUIT":
                w("221 bye")
                return
            elif cmd.startswith("EHLO"):
                w("250 arato-test")
            else:
                w("250 ok")


def demarrer(hote: str, port: int) -> bool:
    """Démarre la boîte de test si l'adresse est locale et le port libre. Retourne True si elle écoute (ou écoutait déjà)."""
    if str(hote).strip().lower() not in ("localhost", "127.0.0.1", "::1"):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True                                   # un serveur (par ex. scripts/smtp_debug.py) écoute déjà
    except OSError:
        pass
    try:
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), _Handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, name="smtp-test", daemon=True).start()
        log.info("Boîte d'envoi de test démarrée sur localhost:%s (copies dans data/outbox)", port)
        return True
    except OSError as e:
        log.warning("Boîte d'envoi de test impossible sur le port %s : %s", port, e)
        return False
