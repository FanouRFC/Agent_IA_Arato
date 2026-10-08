"""Notification d'affectation à la création (module déterministe, fastapi-mail). Aucun accès pour l'agent."""
import asyncio

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from .config import settings

_conf = ConnectionConfig(
    MAIL_USERNAME=settings.mail_username, MAIL_PASSWORD=settings.mail_password, MAIL_FROM=settings.mail_from,
    MAIL_PORT=settings.mail_port, MAIL_SERVER=settings.mail_server, MAIL_STARTTLS=settings.mail_starttls,
    MAIL_SSL_TLS=settings.mail_ssl_tls, USE_CREDENTIALS=bool(settings.mail_username), VALIDATE_CERTS=False)


def affectation_text(nom: str, titre: str, ticket_id: int, echeance) -> str:
    return (f"Bonjour {nom},\n\nLe ticket T-{ticket_id:03d} « {titre} » vous a été affecté.\n"
            f"Échéance : {echeance}.\n\nCordialement,\nArato – suivi des tâches")


def send_assignment(email: str, texte: str, titre: str) -> None:
    """Appelé depuis un thread (endpoint synchrone) : lève une exception en cas d'échec."""
    msg = MessageSchema(subject=f"Nouveau ticket : {titre}", recipients=[email], body=texte,
                        subtype=MessageType.plain)
    asyncio.run(FastMail(_conf).send_message(msg))
