"""Photos de profil des comptes responsables : fichiers stockés sur disque (data/avatars), aucune colonne ajoutée à la base.
Chaque image est recadrée au carré, réduite à 256 px et enregistrée en JPEG."""
import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent.parent / "data" / "avatars"
MAX_BYTES = 5 * 1024 * 1024
TAILLE = 256
Image.MAX_IMAGE_PIXELS = 40_000_000


class PhotoInvalide(ValueError):
    pass


def chemin(stem: str) -> Path:
    return ROOT / f"{stem}.jpg"


def version(stem: str) -> Optional[int]:
    """Date de dernière modification (sert à rafraîchir le cache du navigateur) ; None si pas de photo."""
    p = chemin(stem)
    return int(p.stat().st_mtime) if p.exists() else None


def enregistrer(raw: bytes, stem: str) -> None:
    if not raw:
        raise PhotoInvalide("Fichier vide.")
    if len(raw) > MAX_BYTES:
        raise PhotoInvalide("Image trop lourde (5 Mo maximum).")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise PhotoInvalide("Ce fichier n'est pas une image valide (PNG, JPEG, WebP ou GIF).")
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fond = Image.new("RGB", img.size, (255, 255, 255))
        fond.paste(img, mask=img.split()[-1])
        img = fond
    else:
        img = img.convert("RGB")
    img = ImageOps.fit(img, (TAILLE, TAILLE), Image.Resampling.LANCZOS)
    ROOT.mkdir(parents=True, exist_ok=True)
    img.save(chemin(stem), "JPEG", quality=88, optimize=True)


def supprimer(stem: str) -> None:
    try:
        chemin(stem).unlink()
    except FileNotFoundError:
        pass
