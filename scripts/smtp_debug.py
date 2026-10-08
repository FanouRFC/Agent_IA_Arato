"""Serveur SMTP de test local (remplace MailHog) : affiche les e-mails dans la console.
Usage : python scripts/smtp_debug.py     (nécessite : pip install aiosmtpd)"""
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Debugging
import sys, time

c = Controller(Debugging(sys.stdout), hostname="localhost", port=1025)
c.start()
print("Serveur SMTP de test sur localhost:1025 (Ctrl+C pour arrêter)")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    c.stop()
