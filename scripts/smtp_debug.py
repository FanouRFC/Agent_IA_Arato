"""Serveur SMTP de test local : affiche chaque e-mail reçu dans la console. N'a besoin d'AUCUN paquet à installer (bibliothèque standard).
Usage : python scripts/smtp_debug.py        (écoute sur localhost:1025, comme MAIL_PORT=1025 dans .env)"""
import socketserver
import sys
from email import policy
from email.parser import BytesParser


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())
        w("220 smtp-test ESMTP")
        data, en_data = [], False
        for brut in self.rfile:
            ligne = brut.rstrip(b"\r\n")
            if en_data:
                if ligne == b".":
                    en_data = False
                    m = BytesParser(policy=policy.default).parsebytes(b"\r\n".join(data))
                    corps = m.get_body(preferencelist=("plain",))
                    print("\n" + "=" * 60 + f"\nDe : {m['From']}\nÀ  : {m['To']}\nObjet : {m['Subject']}\n" + "-" * 60)
                    print(corps.get_content() if corps else "(sans corps texte)")
                    sys.stdout.flush()
                    data = []
                    w("250 ok")
                else:
                    data.append(ligne[1:] if ligne.startswith(b"..") else ligne)
                continue
            cmd = ligne.decode(errors="replace").upper()
            if cmd == "DATA":
                en_data = True
                w("354 go")
            elif cmd == "QUIT":
                w("221 bye")
                return
            elif cmd.startswith("EHLO"):
                w("250 smtp-test")
            else:
                w("250 ok")


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 1025), Handler) as srv:
        print("Serveur SMTP de test sur localhost:1025 (Ctrl+C pour arrêter)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
