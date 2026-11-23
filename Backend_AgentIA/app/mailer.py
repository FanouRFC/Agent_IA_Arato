"""Notification d'affectation à la création (module déterministe). Aucun accès pour l'agent.

Envoi par smtplib (bibliothèque standard) : aucune validation de domaine côté Python, donc les adresses de test
(@arato.test) sont acceptées comme les vraies. Chaque e-mail est aussi enregistré en .eml dans data/outbox (copie de
traçabilité). Résultat de chaque envoi : « envoye » (accepté par le serveur SMTP) ou « archive » (serveur injoignable :
le message n'est PAS parti, seule la copie existe). Une vraie erreur (adresse invalide, authentification, destinataire
refusé) lève MailError. Le journal (Administration → Journal) indique, e-mail par e-mail, s'il est parti ou non.
Réglage : MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_STARTTLS, MAIL_SSL_TLS, MAIL_FROM dans .env.
Sécurité AUTOMATIQUE si MAIL_STARTTLS / MAIL_SSL_TLS sont omis : port 465 → SSL ; sinon STARTTLS dès que le serveur le propose
(port 587 : Gmail, Outlook, Brevo…). Tous les e-mails d'un lot partent sur UNE seule connexion (rapide, et un serveur
injoignable n'est testé qu'une fois)."""
import datetime as dt
import html
import re
import smtplib
import logging
import socket
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .config import Settings, settings

log = logging.getLogger("mailer")
TIMEOUT, ESSAIS, PAUSE = 12, 2, 1.5      # délai de connexion (s), nombre de tentatives sur panne passagère, pause entre deux
OUTBOX = Path(__file__).resolve().parent.parent / "data" / "outbox"
_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(Exception):
    """Échec d'envoi, avec un message exploitable par l'utilisateur."""


def _jour(d) -> str:
    try:
        return dt.date.fromisoformat(str(d)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(d)


def affectation_text(nom: str, titre: str, ticket_id: int, echeance, projet: str = "") -> str:
    lieu = f" du projet « {projet} »" if projet else ""
    return (f"Bonjour {nom},\n\nLe ticket T-{ticket_id:03d} « {titre} »{lieu} vous a été affecté.\n"
            f"Échéance : {_jour(echeance)}.\n\nCordialement,\nArato – suivi des tâches")


def _html(texte: str) -> str:
    paras = "".join(f"<p style='margin:0 0 12px'>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in texte.split("\n\n"))
    return ("<div style=\"font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#1A2040;max-width:560px;margin:auto\">"
            "<div style='height:6px;background:linear-gradient(90deg,#5281EB,#8860CF);border-radius:6px'></div>"
            f"<div style='padding:18px 4px'>{paras}</div></div>")


CLES = ("server", "port", "username", "password", "starttls", "ssl", "sender")


_ENV = Path(__file__).resolve().parent.parent / ".env"


def _reglages() -> Settings:
    """Réglages d'envoi RELUS à chaque envoi : une modification du fichier .env est prise en compte sans redémarrer le serveur
    (le rechargement automatique ne surveille que les fichiers .py : l'ancienne configuration restait donc en mémoire)."""
    try:
        return Settings(_env_file=_ENV) if _ENV.exists() else Settings()
    except Exception as e:
        log.warning("Relecture des réglages d'e-mail impossible (%s) : réglages déjà chargés conservés", e)
        return settings


def config_defaut() -> dict:
    r = _reglages()
    return {"server": r.mail_server.strip(), "port": r.mail_port, "username": (r.mail_username or "").strip(),
            "password": r.mail_password or "", "starttls": r.mail_starttls, "ssl": r.mail_ssl_tls,
            "sender": (r.mail_from or "").strip()}


def config_effective(enregistree: dict | None) -> dict:
    cfg = config_defaut()
    for k in CLES:
        if enregistree and enregistree.get(k) not in (None, ""):
            cfg[k] = enregistree[k]
    cfg["port"] = int(cfg["port"])
    if any(h in str(cfg["server"]).lower() for h in ("gmail.com", "googlemail.com")):
        cfg["password"] = str(cfg["password"]).replace(" ", "")     # le mot de passe d'application Google s'affiche par blocs séparés d'espaces
    # Gmail, Outlook… refusent (ou réécrivent) un expéditeur qui n'est pas le compte authentifié : tant que MAIL_FROM est
    # resté à sa valeur d'exemple, l'expéditeur est le compte MAIL_USERNAME.
    if cfg["username"] and "@" in str(cfg["username"]) and cfg["sender"] in ("", "agent-ia@arato.mg"):
        cfg["sender"] = cfg["username"]
    return cfg


class Injoignable(Exception):
    """Le serveur SMTP n'a pas pu être joint (réseau). Distinct des refus du serveur (authentification, chiffrement,
    destinataire…) qui, eux, prouvent que le serveur est bien joignable."""


def _injoignable(e: Exception) -> bool:
    """Vrai pour une vraie panne réseau. ATTENTION : smtplib.SMTPException et ssl.SSLError héritent d'OSError ; sans cette
    distinction, une authentification refusée ou un chiffrement manquant étaient pris pour un serveur « injoignable »."""
    if isinstance(e, Injoignable):
        return True
    if isinstance(e, (smtplib.SMTPException, ssl.SSLError)):
        return False
    return isinstance(e, (ConnectionError, socket.timeout, TimeoutError, socket.gaierror, OSError))


def _expliquer(e: Exception, cfg: dict) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "authentification SMTP refusée : identifiant ou mot de passe incorrect (pour Gmail, utiliser un mot de passe d'application)"
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return "le serveur SMTP n'accepte pas cette méthode d'authentification ou de chiffrement"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "adresse du destinataire refusée par le serveur SMTP"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"expéditeur {cfg['sender']} refusé par le serveur SMTP (il doit correspondre au compte utilisé)"
    if isinstance(e, ssl.SSLError):
        return "échec du chiffrement TLS : vérifiez le port (587 = STARTTLS, 465 = SSL)"
    if isinstance(e, smtplib.SMTPServerDisconnected):
        etape = getattr(e, "etape", "")
        suite = f" (étape : {etape}, mode {securite(cfg)}, port {cfg['port']})" if etape else ""
        return "le serveur SMTP a fermé la connexion (identifiants refusés, ou chiffrement attendu sur ce port)" + suite
    if isinstance(e, smtplib.SMTPResponseException):
        return f"réponse du serveur SMTP : {e.smtp_code} {bytes(e.smtp_error).decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"
    return str(e) or e.__class__.__name__


def _transitoire(e: Exception) -> bool:
    """Panne passagère qui mérite une seconde tentative (réponse 4xx, coupure de connexion, délai dépassé)."""
    return isinstance(e, (smtplib.SMTPServerDisconnected, Injoignable)) or \
        (isinstance(e, smtplib.SMTPResponseException) and 400 <= e.smtp_code < 500 and not isinstance(e, smtplib.SMTPSenderRefused))


def _message(email: str, texte: str, sujet: str, expediteur: str) -> EmailMessage:
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = sujet, expediteur, email
    m["Date"], m["Message-ID"] = formatdate(localtime=True), make_msgid(domain="arato.mg")
    m.set_content(texte)
    m.add_alternative(_html(texte), subtype="html")
    return m


def _archiver(m: EmailMessage, email: str) -> None:
    try:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        nom = re.sub(r"[^a-z0-9]+", "_", email.lower())
        (OUTBOX / f"{dt.datetime.now():%Y%m%d_%H%M%S_%f}_{nom}.eml").write_bytes(bytes(m))
    except OSError:
        pass   # l'archive est un confort, jamais une cause d'échec


def securite(cfg: dict) -> str:
    """Mode de chiffrement retenu : « SSL », « STARTTLS » ou « automatique » (STARTTLS dès que le serveur le propose)."""
    if cfg["ssl"] or (cfg["ssl"] is None and cfg["port"] == 465):
        return "SSL"
    if cfg["starttls"] or (cfg["starttls"] is None and cfg["port"] == 587):
        return "STARTTLS"
    return "automatique" if cfg["starttls"] is None else "aucun"


def _ouvrir_mode(cfg: dict, mode: str) -> smtplib.SMTP:
    """Ouvre la connexion avec UN mode de chiffrement. Seule une panne RÉSEAU lève Injoignable ; chiffrement et authentification
    lèvent leurs propres erreurs, étiquetées avec l'étape atteinte (attribut « etape ») pour un diagnostic précis."""
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # certificats auto-signés tolérés (réseau interne)
    etape = "connexion"
    try:
        if mode == "SSL":
            s: smtplib.SMTP = smtplib.SMTP_SSL(cfg["server"], cfg["port"], timeout=TIMEOUT, context=ctx)
        else:
            s = smtplib.SMTP(cfg["server"], cfg["port"], timeout=TIMEOUT)
    except (smtplib.SMTPException, ssl.SSLError) as e:
        e.etape = etape
        raise
    except OSError as e:
        raise Injoignable(str(e)) from e
    try:
        etape = "dialogue EHLO"
        s.ehlo()
        if mode != "SSL" and (mode == "STARTTLS" or (mode == "automatique" and s.has_extn("starttls"))):
            etape = "passage en STARTTLS"
            s.starttls(context=ctx)
            s.ehlo()
        if cfg["username"]:
            etape = "authentification"
            s.login(cfg["username"], cfg["password"])
    except Exception as e:
        s.close()
        e.etape = etape
        raise
    return s


def _ouvrir(cfg: dict) -> smtplib.SMTP:
    """Ouvre la connexion. Si le serveur coupe la connexion (ou refuse la poignée de main TLS) avec le mode configuré, l'AUTRE mode
    est essayé automatiquement sur le même port (cas classique : SSL demandé sur le port 587, ou STARTTLS sur le port 465).
    Un refus d'authentification n'est jamais rejoué : c'est une vraie erreur d'identifiants."""
    mode = securite(cfg)
    try:
        return _ouvrir_mode(cfg, mode)
    except (smtplib.SMTPServerDisconnected, ssl.SSLError, ConnectionResetError) as e:
        autre = "STARTTLS" if mode == "SSL" else "SSL" if mode in ("STARTTLS", "automatique") else None
        if autre is None or getattr(e, "etape", "") == "authentification":
            raise
        log.warning("SMTP %s:%s : connexion coupée en mode %s (%s) ; nouvel essai en mode %s",
                    cfg["server"], cfg["port"], mode, e.__class__.__name__, autre)
        try:
            return _ouvrir_mode(cfg, autre)
        except (smtplib.SMTPException, ssl.SSLError, OSError):
            raise e from None                                    # l'erreur d'origine est la plus parlante


def _tentative(cfg: dict, prets: list, resultats: list) -> bool:
    """Une tentative sur UNE connexion pour les messages sans résultat définitif. Retourne True si une nouvelle tentative
    peut réussir (panne passagère)."""
    restants = [(k, m) for k, m in prets if resultats[k] is None]
    if not restants:
        return False
    try:
        s = _ouvrir(cfg)
    except Exception as e:
        if _injoignable(e):
            statut, detail = "archive", (f"serveur SMTP {cfg['server']}:{cfg['port']} injoignable : le message n'est pas parti "
                                         "(une copie est conservée dans data/outbox)")
        else:
            statut, detail = "echec", _expliquer(e, cfg)
        for k, _ in restants:
            resultats[k] = (statut, detail)
        return _transitoire(e)
    reessayer = False
    with s:
        for k, m in restants:
            try:
                s.send_message(m)
                resultats[k] = ("envoye", f"remis au serveur {cfg['server']}:{cfg['port']}")
            except smtplib.SMTPServerDisconnected as e:      # connexion perdue : on recommence pour ce message et les suivants
                resultats[k] = ("echec", _expliquer(e, cfg))
                reessayer = True
                break
            except smtplib.SMTPException as e:              # refus propre à CE message : les autres continuent
                resultats[k] = ("echec", _expliquer(e, cfg))
                reessayer = reessayer or _transitoire(e)
    return reessayer


def send_batch(items: list[tuple[str, str, str]], enregistree: dict | None = None) -> list[tuple[str, str]]:
    """Envoie des e-mails (adresse, texte, sujet) sur UNE connexion. Retourne, dans le même ordre, (statut, détail) avec
    statut = « envoye » (remis au serveur SMTP) | « archive » (serveur injoignable : seul le fichier .eml existe) |
    « echec » (adresse invalide, authentification, destinataire ou expéditeur refusé…). Ne lève jamais d'exception."""
    cfg = config_effective(enregistree)
    resultats: list[tuple[str, str] | None] = [None] * len(items)
    prets: list[tuple[int, EmailMessage]] = []
    for k, (email, texte, sujet) in enumerate(items):
        email = (email or "").strip()
        if not _ADRESSE.match(email):
            resultats[k] = ("echec", f"adresse e-mail invalide « {email} »")
            continue
        m = _message(email, texte, sujet, cfg["sender"])
        _archiver(m, email)
        prets.append((k, m))
    for essai in range(ESSAIS):
        if not _tentative(cfg, prets, resultats):
            break
        if essai + 1 < ESSAIS:
            time.sleep(PAUSE)
            for k, _ in prets:                       # les échecs passagers sont retentés ; les succès restent acquis
                if resultats[k] and resultats[k][0] != "envoye":
                    resultats[k] = None
    return [r or ("echec", "envoi non effectué") for r in resultats]


def send(email: str, texte: str, sujet: str, enregistree: dict | None = None) -> tuple[str, str]:
    """Un seul e-mail. Retourne ("envoye" | "archive", détail) ; lève MailError pour une vraie erreur."""
    statut, detail = send_batch([(email, texte, sujet)], enregistree)[0]
    if statut == "echec":
        raise MailError(detail)
    return statut, detail


def send_assignment(email: str, texte: str, titre: str, enregistree: dict | None = None) -> str:
    return send(email, texte, f"Nouveau ticket : {titre}", enregistree)[0]


def diagnostic(enregistree: dict | None = None) -> dict:
    """État de la configuration d'envoi, sans jamais exposer le mot de passe."""
    cfg = config_effective(enregistree)
    return {"serveur": cfg["server"], "port": cfg["port"], "expediteur": cfg["sender"], "securite": securite(cfg),
            "authentification": bool(cfg["username"]),
            "local": cfg["server"] in ("localhost", "127.0.0.1", "::1") and not cfg["username"]}
