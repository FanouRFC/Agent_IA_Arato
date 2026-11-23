import datetime as dt
import hashlib
import hmac
import os
import threading
import time

import jwt
from sqlalchemy import select
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer = HTTPBearer(auto_error=False)


def hash_password(p: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 200_000).hex()


def verify_password(p: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(p, bytes.fromhex(salt)), stored)
    except ValueError:                      # empreinte illisible : mot de passe refusé, jamais d'erreur 500
        return False


_FAUSSE_EMPREINTE = hash_password("aucun-compte")      # égalise le temps de réponse quand l'e-mail n'existe pas


class LimiteConnexion:
    """Limite les essais de connexion échoués (par couple adresse IP + e-mail) : MAX échecs sur FENETRE secondes, puis blocage
    temporaire. En mémoire (un seul processus) : suffisant contre l'énumération et la force brute d'un mot de passe."""
    MAX, FENETRE = 5, 300

    def __init__(self):
        self._echecs: dict[str, list[float]] = {}
        self._verrou = threading.Lock()

    def _purger(self, cle: str, maintenant: float) -> list[float]:
        liste = [t for t in self._echecs.get(cle, []) if maintenant - t < self.FENETRE]
        if liste:
            self._echecs[cle] = liste
        else:
            self._echecs.pop(cle, None)
        return liste

    def verifier(self, cle: str):
        with self._verrou:
            liste = self._purger(cle, time.monotonic())
            if len(liste) >= self.MAX:
                attente = int(self.FENETRE - (time.monotonic() - liste[0])) + 1
                raise HTTPException(429, f"Trop de tentatives de connexion. Réessayez dans {max(1, attente // 60 + 1)} min.",
                                    headers={"Retry-After": str(attente)})

    def echec(self, cle: str):
        with self._verrou:
            self._purger(cle, time.monotonic())
            self._echecs.setdefault(cle, []).append(time.monotonic())

    def succes(self, cle: str):
        with self._verrou:
            self._echecs.pop(cle, None)


limite_connexion = LimiteConnexion()


def create_token(email: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)
    return jwt.encode({"sub": email, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_admin(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Accès réservé aux comptes responsables (tous ont exactement les mêmes droits). Renvoie l'e-mail du compte."""
    if not cred:
        raise HTTPException(401, "Connexion requise")
    try:
        email = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Session invalide ou expirée")
    from .db import SessionLocal          # import tardif : évite un import circulaire
    from .models import User
    with SessionLocal() as db:
        actif = db.scalars(select(User.actif).where(User.email == email)).first()
    if not actif:                          # compte supprimé ou désactivé : la session n'est plus valable
        raise HTTPException(401, "Session invalide ou expirée")
    return email
