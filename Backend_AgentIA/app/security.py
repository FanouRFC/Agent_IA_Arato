import datetime as dt
import hashlib
import hmac
import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer = HTTPBearer(auto_error=False)


def hash_password(p: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 200_000).hex()


def verify_password(p: str, stored: str) -> bool:
    salt, _ = stored.split("$")
    return hmac.compare_digest(hash_password(p, bytes.fromhex(salt)), stored)


def create_token(nom: str) -> str:
    exp = dt.datetime.utcnow() + dt.timedelta(hours=12)
    return jwt.encode({"sub": nom, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_admin(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Accès réservé au haut responsable."""
    if not cred:
        raise HTTPException(401, "Connexion requise")
    try:
        return jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Session invalide ou expirée")
