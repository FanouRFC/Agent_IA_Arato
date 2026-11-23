"""Outils Python DÉTERMINISTES. Le LLM les appelle et interprète leurs résultats ; il ne calcule jamais."""
import datetime as dt
import difflib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from .calendar_utils import bd_between

log = logging.getLogger(__name__)


# ---------- Extraction du document ----------
def clean_text(t: str) -> str:
    t = t.replace("\x00", "")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


class ExtractionError(Exception):
    """Erreur d'extraction avec un message lisible par l'utilisateur."""


# Formats pris en charge (les routes et le front s'appuient sur ces constantes)
EXT_PDF = {".pdf"}
EXT_TEXTE = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".log", ".html", ".htm"}
EXT_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
EXT_OFFICE = {".docx", ".pptx", ".xlsx"}
# Anciens formats / OpenDocument / RTF : convertis via LibreOffice (s'il est installé)
EXT_CONVERTIS = {".doc": "docx", ".odt": "docx", ".rtf": "docx",
                 ".ppt": "pptx", ".odp": "pptx",
                 ".xls": "xlsx", ".ods": "xlsx"}
EXT_OK = EXT_PDF | EXT_TEXTE | EXT_IMAGE | EXT_OFFICE | set(EXT_CONVERTIS)

MAX_IMAGE_FRAMES = 20       # TIFF / GIF multi-pages
MAX_XLSX_LIGNES = 2000      # par feuille

# ----- Réglages OCR (EasyOCR), surchargeables par variables d'environnement -----
MAX_OCR_PAGES = int(os.getenv("OCR_MAX_PAGES", "20"))        # un PDF scanné est lu par OCR sur N pages au plus (EasyOCR est plus lent que Tesseract sur CPU)
OCR_DPI = int(os.getenv("OCR_DPI", "150"))                   # résolution de rendu des pages PDF
OCR_LANGUES = [x.strip() for x in os.getenv("OCR_LANGUES", "fr,en").split(",") if x.strip()]
OCR_MAX_COTE = int(os.getenv("OCR_MAX_COTE", "2600"))        # une image plus grande est réduite (vitesse et mémoire)
OCR_MIN_COTE = 800                                           # une image plus petite est agrandie (meilleure reconnaissance)
OCR_MODEL_DIR = os.getenv("OCR_MODEL_DIR") or None           # dossier des modèles (défaut EasyOCR : ~/.EasyOCR/model)
OCR_GPU = os.getenv("OCR_GPU", "auto").lower()               # "auto", "1" ou "0"


def _pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ExtractionError("PDF protégé par un mot de passe : retirez la protection puis réessayez.")
        except ExtractionError:
            raise
        except Exception:
            raise ExtractionError("PDF protégé par un mot de passe : retirez la protection puis réessayez.")
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def _docx(path: str) -> str:
    import docx
    d = docx.Document(path)
    text = "\n".join(par.text for par in d.paragraphs)
    for tb in d.tables:
        for row in tb.rows:
            text += "\n" + " | ".join(c.text for c in row.cells)
    return text


def _pptx_formes(formes, out: list) -> None:
    """Texte des formes d'une diapositive (y compris groupes et tableaux). Une forme illisible est ignorée, jamais fatale."""
    for sh in formes:
        try:
            if getattr(sh, "shapes", None) is not None:                          # groupe de formes
                _pptx_formes(sh.shapes, out)
                continue
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                txt = sh.text_frame.text.strip()
                if txt:
                    out.append(txt)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    out.append(" | ".join(c.text for c in row.cells))
        except Exception:
            log.warning("PowerPoint : une forme n'a pas pu être lue, elle est ignorée", exc_info=True)


def _pptx(path: str) -> str:
    from pptx import Presentation
    out: list[str] = []
    for i, slide in enumerate(Presentation(path).slides, 1):
        out.append(f"--- Diapositive {i} ---")
        _pptx_formes(slide.shapes, out)
        try:
            if slide.has_notes_slide:
                cadre = slide.notes_slide.notes_text_frame      # peut valoir None si la page de notes n'a pas de zone de texte
                notes = cadre.text.strip() if cadre is not None else ""
                if notes:
                    out.append("Notes : " + notes)
        except Exception:
            log.warning("PowerPoint : notes de la diapositive %s illisibles", i, exc_info=True)
    return "\n".join(out)


def _xlsx(path: str) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        out.append(f"--- Feuille {ws.title} ---")
        for n, row in enumerate(ws.iter_rows(values_only=True)):
            if n >= MAX_XLSX_LIGNES:
                out.append("[… lignes suivantes ignorées]")
                break
            if any(c is not None for c in row):
                out.append(" | ".join("" if c is None else str(c) for c in row))
    wb.close()
    return "\n".join(out)


class _HtmlTexte(HTMLParser):
    _IGNORES = {"script", "style", "noscript", "head"}
    _BLOCS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORES:
            self._skip += 1
        elif tag in self._BLOCS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self._IGNORES and self._skip:
            self._skip -= 1
        elif tag in self._BLOCS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def _html(path: str) -> str:
    p = _HtmlTexte()
    p.feed(_texte_brut(path))
    return "".join(p.out)


def _texte_brut(path: str) -> str:
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="ignore")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


# ----- OCR EasyOCR (images et PDF scannés) -----
_LECTEUR = None                       # instance unique d'easyocr.Reader (chargement coûteux : une seule fois par processus)
_VERROU_INIT = threading.Lock()       # protège le chargement des modèles
_VERROU_LECTURE = threading.Lock()    # une seule reconnaissance à la fois (le Reader n'est pas garanti thread-safe)


def _gpu_actif() -> bool:
    if OCR_GPU in ("1", "true", "oui"):
        return True
    if OCR_GPU in ("0", "false", "non"):
        return False
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _lecteur():
    """Retourne le lecteur EasyOCR, chargé à la première utilisation (les modèles sont téléchargés au tout premier lancement)."""
    global _LECTEUR
    if _LECTEUR is not None:
        return _LECTEUR
    with _VERROU_INIT:
        if _LECTEUR is None:
            try:
                import easyocr
            except ImportError:
                raise ExtractionError("Lecture d'images indisponible : installez les paquets « easyocr » et « pillow » sur le serveur.")
            try:
                _LECTEUR = easyocr.Reader(OCR_LANGUES, gpu=_gpu_actif(), verbose=False,
                                          model_storage_directory=OCR_MODEL_DIR)
            except Exception:
                log.exception("Chargement d'EasyOCR impossible (langues %s)", OCR_LANGUES)
                raise ExtractionError("Le moteur de reconnaissance de texte n'a pas pu démarrer : modèles EasyOCR absents "
                                      "(premier lancement sans connexion internet ?). Contactez l'administrateur.")
    return _LECTEUR


def prechauffer_ocr() -> None:
    """À appeler au démarrage du serveur (en tâche de fond) : charge les modèles pour que la première analyse d'un scan ne soit pas lente."""
    try:
        _lecteur()
        log.info("EasyOCR prêt (langues %s)", OCR_LANGUES)
    except Exception as e:
        log.warning("EasyOCR non préchargé : %s", e)


def _ocr(img) -> str:
    """OCR d'une image PIL avec EasyOCR. Retourne le texte, paragraphes séparés par des retours à la ligne."""
    try:
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError:
        raise ExtractionError("Lecture d'images indisponible : installez les paquets « easyocr », « pillow » et « numpy ».")
    img = ImageOps.exif_transpose(img).convert("RGB")
    cote = max(img.size)
    if cote > OCR_MAX_COTE:                                   # très grande image : réduite pour limiter temps et mémoire
        f = OCR_MAX_COTE / cote
        img = img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.LANCZOS)
    elif cote < OCR_MIN_COTE:                                 # petite image : agrandie pour une meilleure reconnaissance
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    lecteur = _lecteur()
    with _VERROU_LECTURE:
        try:
            blocs = lecteur.readtext(np.asarray(img), detail=0, paragraph=True)
        except Exception:
            log.exception("EasyOCR : échec de la reconnaissance")
            raise ExtractionError("La reconnaissance de texte a échoué sur cette image. Essayez avec une image plus nette.")
    return "\n".join(b.strip() for b in blocs if b and b.strip())


def _image(path: str) -> str:
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        raise ExtractionError("Lecture d'images indisponible : installez le paquet « pillow ».")
    out = []
    with Image.open(path) as im:
        for n, frame in enumerate(ImageSequence.Iterator(im)):
            if n >= MAX_IMAGE_FRAMES:
                break
            out.append(_ocr(frame.copy()))
    return "\n".join(out)


def _pdf_ocr(path: str) -> str:
    """PDF scanné : chaque page est rendue en image puis lue par OCR (PyMuPDF si présent, sinon pdf2image + poppler)."""
    from PIL import Image
    try:
        import fitz                                            # PyMuPDF : aucune dépendance système
    except ImportError:
        fitz = None
    if fitz is not None:
        out = []
        with fitz.open(path) as doc:
            for n, page in enumerate(doc):
                if n >= MAX_OCR_PAGES:
                    break
                pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
                out.append(_ocr(Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
        return "\n".join(out)
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise ExtractionError("PDF scanné : installez « pymupdf » (ou « pdf2image » avec poppler) pour activer la reconnaissance de texte.")
    try:
        pages = convert_from_path(path, dpi=OCR_DPI, first_page=1, last_page=MAX_OCR_PAGES)
    except Exception:
        raise ExtractionError("PDF scanné illisible : poppler est probablement absent du serveur.")
    return "\n".join(_ocr(p) for p in pages)


# ----- Anciens formats (.doc, .ppt, .xls, .odt, .odp, .ods, .rtf) : conversion LibreOffice -----
def _convertir(path: str, cible: str) -> str:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise ExtractionError(f"Ce format ancien nécessite LibreOffice sur le serveur. Enregistrez le fichier en .{cible} puis réessayez.")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([exe, "--headless", "--convert-to", cible, "--outdir", tmp, path],
                           check=True, timeout=120, capture_output=True)
        except Exception:
            raise ExtractionError(f"Conversion impossible : enregistrez le fichier en .{cible} puis réessayez.")
        res = next(Path(tmp).glob(f"*.{cible}"), None)
        if not res:
            raise ExtractionError(f"Conversion impossible : enregistrez le fichier en .{cible} puis réessayez.")
        return _extraire(str(res))


def _extraire(path: str) -> str:
    """Texte brut (non nettoyé) selon l'extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        txt = _pdf(path)
        if len(txt.strip()) < 30:                              # peu ou pas de texte : PDF scanné, on tente la reconnaissance
            ocr = _pdf_ocr(path)
            if len(ocr.strip()) > len(txt.strip()):
                txt = ocr
        return txt
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext == ".xlsx":
        return _xlsx(path)
    if ext in EXT_IMAGE:
        return _image(path)
    if ext in (".html", ".htm"):
        return _html(path)
    if ext in EXT_CONVERTIS:
        return _convertir(path, EXT_CONVERTIS[ext])
    return _texte_brut(path)                                   # txt, md, csv, tsv, json, xml, log…


def extract_text(path: str) -> str:
    """Extrait le texte d'un cahier des charges : PDF (même scanné), Word, PowerPoint, Excel, image (OCR), texte, HTML, etc."""
    ext = Path(path).suffix.lower()
    if ext not in EXT_OK:
        raise ExtractionError("Format non pris en charge.")
    try:
        return clean_text(_extraire(path))
    except ExtractionError:
        raise
    except ImportError as e:            # module Python absent du serveur : message précis au lieu de « fichier illisible »
        paquets = {"pptx": "python-pptx", "docx": "python-docx", "fitz": "pymupdf", "openpyxl": "openpyxl", "pypdf": "pypdf"}
        nom = (e.name or "").split(".")[0]
        log.error("Module manquant pour lire %s : %s", ext, e)
        raise ExtractionError(f"Le serveur ne peut pas lire ce format : le module « {paquets.get(nom, nom)} » n'est pas installé "
                              f"(pip install {paquets.get(nom, nom)}).")
    except (zipfile.BadZipFile, KeyError):
        if ext in EXT_OFFICE:           # un .pptx / .docx / .xlsx est une archive zip : sinon fichier corrompu ou ancien format renommé
            raise ExtractionError(f"Ce fichier n'est pas un vrai {ext} (corrompu, ou ancien format simplement renommé). "
                                  "Ouvrez-le dans Office et enregistrez-le de nouveau en " + ext + ".")
        raise


# ---------- Dépendances et cohérence ----------
def check_dependencies(taches: list[dict]) -> dict:
    """Cycles, références inconnues, ordre d'exécution (tri topologique)."""
    ids = {t["id"] for t in taches}
    deps = {t["id"]: list(t.get("depend_de") or []) for t in taches}
    unknown = [(i, d) for i, ds in deps.items() for d in ds if d not in ids or d == i]
    indeg = {i: len([d for d in ds if d in ids and d != i]) for i, ds in deps.items()}
    ordre, queue = [], sorted(i for i, n in indeg.items() if n == 0)
    while queue:
        n = queue.pop(0)
        ordre.append(n)
        for i, ds in deps.items():
            if n in ds and i != n:
                indeg[i] -= 1
                if indeg[i] == 0:
                    queue.append(i)
    cycle = sorted(set(ids) - set(ordre))
    return {"ok": not unknown and not cycle, "references_invalides": unknown, "taches_en_cycle": cycle,
            "ordre": ordre if not cycle else []}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


# Priorités : vocabulaire actuel « priorité / secondaire / bonus » ; l'ancien « haute / moyenne / basse » est converti.
PRIORITES = ("priorité", "secondaire", "bonus")
_PRIO_ALIAS = {"priorite": "priorité", "priorité": "priorité", "haute": "priorité", "high": "priorité",
               "secondaire": "secondaire", "moyenne": "secondaire", "medium": "secondaire",
               "bonus": "bonus", "basse": "bonus", "low": "bonus"}


def normaliser_priorite(v) -> str | None:
    """Ramène toute valeur connue (nouvelle ou ancienne, avec ou sans accent ou majuscule) à priorité / secondaire / bonus ; None si inconnue."""
    return _PRIO_ALIAS.get(str(v or "").strip().lower())


def check_coherence(taches: list[dict], texte_document: str) -> dict:
    """Doublons, manques, contradictions, fidélité au document."""
    problemes, doc = [], _norm(texte_document)
    for i, a in enumerate(taches):
        for b in taches[i + 1:]:
            if difflib.SequenceMatcher(None, _norm(a["titre"]), _norm(b["titre"])).ratio() > 0.88:
                problemes.append(f"Doublon probable : tâches {a['id']} et {b['id']}")
    for t in taches:
        n = t["id"]
        if not (t.get("description") or "").strip():
            problemes.append(f"Tâche {n} : description manquante")
        if not isinstance(t.get("duree_estimee_jours"), int) or t["duree_estimee_jours"] < 1:
            problemes.append(f"Tâche {n} : durée estimée invalide (entier ≥ 1 jour)")
        elif t["duree_estimee_jours"] > 60:
            problemes.append(f"Tâche {n} : durée de {t['duree_estimee_jours']} jours, à découper")
        if normaliser_priorite(t.get("priorite")) is None:
            problemes.append(f"Tâche {n} : priorité invalide (priorité, secondaire ou bonus)")
        src = _norm(t.get("source_dans_document", ""))
        if not src or src not in doc:
            problemes.append(f"Tâche {n} : source_dans_document absente ou non copiée à l'identique du document")
    return {"ok": not problemes, "problemes": problemes}


# ---------- Critères d'acceptation : nettoyage (saisie humaine) et contrôle de fidélité (sortie du LLM) ----------
MAX_CRITERES = 6                 # par tâche générée par l'agent
MAX_CRITERE_CHARS = 400
_MOTS_VIDES = frozenset("""le la les un une des du de d l au aux et ou en dans sur pour par avec sans est sont etre doit doivent
peut peuvent ce cette ces son sa ses leur leurs qui que quoi dont ainsi afin plus moins tout tous toute toutes chaque lors apres
avant entre vers sous chez ne pas non oui aussi comme meme cela ceci etre avoir fait faire sera seront ete""".split())
# Formules creuses : un critère qui ne dit rien de vérifiable n'est jamais retenu.
_GENERIQUES = ("le travail est termine", "la tache est terminee", "la tache est realisee", "la tache est finalisee",
               "conforme aux attentes", "fonctionne correctement", "fonctionne bien", "de bonne qualite", "de qualite",
               "repond aux besoins", "satisfait le client", "donne satisfaction", "sans aucun probleme", "est complete",
               "est achevee", "livrable conforme", "objectifs atteints", "objectif atteint")


def _sans_accent(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if not unicodedata.combining(c)).lower()


def _mots_utiles(s: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]{4,}", _sans_accent(s)) if m not in _MOTS_VIDES}


def _nombres(s: str) -> set[str]:
    return {x.replace(",", ".") for x in re.findall(r"\d+(?:[.,]\d+)?", s or "")}


def clean_criteria(items, max_items: int = 12, max_len: int = MAX_CRITERE_CHARS) -> list[str]:
    """Nettoyage d'une liste de critères (saisie ou sortie brute) : puces et numéros retirés, espaces normalisés,
    doublons supprimés, longueur bornée. Aucun jugement de fond ici."""
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        items = [items]
    out, vus = [], set()
    for x in items:
        if isinstance(x, dict):
            x = x.get("texte") or x.get("critere") or x.get("description") or ""
        t = " ".join(str(x or "").split())
        t = re.sub(r"^(?:[-•*·▪●]+|\d{1,2}[.)])\s*", "", t).strip()
        k = _norm(t)
        if len(t) < 5 or k in vus:
            continue
        vus.add(k)
        out.append(t[:max_len].rstrip())
        if len(out) >= max_items:
            break
    return out


def criteres_par_defaut(titre: str, description: str = "", source: str = "") -> list[str]:
    """Critères d'acceptation PAR DÉFAUT (1 à 3), construits uniquement à partir de l'énoncé de la tâche : ils ne contiennent aucun fait,
    chiffre ou technologie absent du titre / de la description / de la source. Utilisés quand le modèle ne propose rien de recevable
    (document peu détaillé, modèle indisponible, ticket ancien) : une tâche a TOUJOURS au moins un critère vérifiable.
    Le texte est stable (même entrée → même sortie) pour que les cases cochées restent associées au critère."""
    titre = " ".join((titre or "").split()).rstrip(" .;:") or "la tâche"
    enonce = " ".join((description or source or "").split()).strip()
    crit = []
    if enonce and _norm(enonce)[:60] != _norm(titre)[:60]:
        crit.append(f"Le livrable de « {titre[:120]} » répond à l'exigence suivante : {enonce[:260].rstrip(' .;:')}.")
    else:
        crit.append(f"Le livrable de « {titre[:160]} » est réalisé et utilisable tel que décrit dans le titre de la tâche.")
    crit.append("Le résultat est présenté au responsable (démonstration ou livrable) qui constate qu'il est conforme à l'exigence.")
    crit.append("Aucune anomalie bloquante n'est ouverte sur cette tâche au moment de la validation.")
    return crit


def assurer_criteres(criteres, titre: str, description: str = "", source: str = "") -> tuple[list[str], bool]:
    """Garantit au moins un critère : retourne (critères, par_defaut). Les critères existants sont conservés tels quels."""
    propres = clean_criteria(criteres)
    if propres:
        return propres, False
    return criteres_par_defaut(titre, description, source), True


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def taches_similaires(a: dict, b: dict) -> bool:
    """Deux tâches répétitives = même exigence reformulée : titres quasi identiques, mêmes mots clés titre+description, ou même passage
    du document (source identique ou contenue dans l'autre)."""
    ta, tb = _mots_utiles(a.get("titre", "")), _mots_utiles(b.get("titre", ""))
    da = ta | _mots_utiles(a.get("description", ""))
    db_ = tb | _mots_utiles(b.get("description", ""))
    if len(ta) >= 2 and len(tb) >= 2 and _jaccard(ta, tb) >= 0.67:
        return True
    if len(da) >= 4 and len(db_) >= 4 and _jaccard(da, db_) >= 0.7:
        return True
    sa, sb = _norm(a.get("source_dans_document", "")), _norm(b.get("source_dans_document", ""))
    if len(sa) >= 30 and len(sb) >= 30 and (sa == sb or sa in sb or sb in sa):
        return True
    return False


def dedoublonner_taches(taches: list[dict]) -> tuple[list[dict], list[str]]:
    """Fusionne les tâches répétitives : la première est conservée (durée la plus longue, dépendances réunies, ambiguïtés réunies), les
    suivantes disparaissent et les dépendances qui les visaient pointent vers la tâche conservée. Retourne (tâches, titres fusionnés)."""
    gardees: list[dict] = []
    alias: dict = {}
    fusionnees: list[str] = []
    for t in taches:
        cible = next((g for g in gardees if taches_similaires(g, t)), None)
        if cible is None:
            gardees.append(t)
            continue
        alias[t["id"]] = cible["id"]
        cible["duree_estimee_jours"] = max(cible.get("duree_estimee_jours", 1), t.get("duree_estimee_jours", 1))
        cible["depend_de"] = list(dict.fromkeys((cible.get("depend_de") or []) + (t.get("depend_de") or [])))
        cible["ambiguites"] = list(dict.fromkeys((cible.get("ambiguites") or []) + (t.get("ambiguites") or [])))
        fusionnees.append(t.get("titre", ""))
    for g in gardees:
        g["depend_de"] = [alias.get(d, d) for d in (g.get("depend_de") or []) if alias.get(d, d) != g["id"]]
    return gardees, fusionnees


def etat_criteres(brut_crm, brut_tache, titre: str, description: str, source: str, coches, statut: str, avancement) -> dict:
    """État des critères d'un ticket, calculé à UN seul endroit (page du ticket, clôture, chat) : critères (au moins un), cases cochées,
    et `cloturable` = non fermé ET avancement CRM à 100 % ET tous les critères cochés."""
    criteres, par_defaut = assurer_criteres(brut_crm or brut_tache or [], titre, description, source)
    coches = set(coches or [])
    valides = [c in coches for c in criteres]
    tous = bool(criteres) and all(valides)
    return {"criteres_acceptation": criteres, "criteres_valides": valides, "criteres_par_defaut": par_defaut,
            "tous_criteres_valides": tous,
            "cloturable": statut != "ferme" and int(avancement or 0) >= 100 and tous}


def validate_criteria(items, contexte: str, max_items: int = MAX_CRITERES) -> tuple[list[str], list[str]]:
    """Contrôle déterministe des critères proposés par le LLM pour UNE tâche. `contexte` = titre, description, source et extrait
    du cahier des charges. Retourne (critères retenus, motifs des rejets). Un critère est rejeté s'il est une formule creuse,
    s'il ne s'appuie sur aucun terme du contexte, s'il est quasi identique à un autre, ou s'il contient un nombre absent du contexte
    (aucune valeur inventée)."""
    ctx_mots, ctx_nb = _mots_utiles(contexte), _nombres(contexte)
    retenus, rejets = [], []
    for c in clean_criteria(items, max_items=30):
        n = _sans_accent(c)
        if len(c) < 12:
            rejets.append(f"trop court : « {c} »")
        elif any(g in n for g in _GENERIQUES):
            rejets.append(f"formule générique : « {c} »")
        elif not (_mots_utiles(c) & ctx_mots):
            rejets.append(f"sans lien avec le document : « {c} »")
        elif _nombres(c) - ctx_nb:
            rejets.append(f"valeur absente du document : « {c} »")
        elif any(difflib.SequenceMatcher(None, n, _sans_accent(r)).ratio() > 0.88 for r in retenus):
            rejets.append(f"doublon : « {c} »")
        else:
            retenus.append(c)
    return retenus[:max_items], rejets


def search_info(ctx: dict, requete: str) -> dict:
    """Recherche limitée aux données autorisées fournies par le backend (aucun service externe)."""
    mots = [m for m in re.findall(r"\w{3,}", requete.lower())]

    def score(txt):
        txt = (txt or "").lower()
        return sum(m in txt for m in mots)

    tickets = sorted(ctx.get("tickets", []), key=lambda t: -score(t["titre"] + " " + (t.get("description") or "")))
    membres = sorted(ctx.get("membres", []), key=lambda m: -score(m["nom"] + " " + m["profil"]))
    return {
        "tickets": [{"id": t["id"], "titre": t["titre"], "statut": t["statut"]} for t in tickets[:25]
                    if score(t["titre"] + " " + (t.get("description") or "")) > 0],
        "membres": [{"id": m["id"], "nom": m["nom"], "profil": m["profil"]} for m in membres[:8]],
        "profils": ctx.get("profils", []),
    }


# ---------- Calcul du suivi (retards, jours de retard, échéances proches) ----------
STATUT_LIB = {"nouveau": "Nouveau", "ouvert": "Ouvert", "en_cours": "En cours", "en_attente": "En attente", "ferme": "Fermé"}


def _j(n: int) -> str:
    return f"{n} jour{'s' if n > 1 else ''}"


def compute_tracking(t: dict, now: dt.datetime, holidays, seuil_jours=2, seuil_av=50,
                     work_end: dt.time = dt.time(17, 0)) -> dict:
    """Règle : date actuelle > échéance ET statut ≠ fermé → en retard. Retourne tous les chiffres de référence."""
    ech = dt.date.fromisoformat(str(t["echeance"]))
    today = now.date()
    r = {"id": t["id"], "statut": t["statut"], "avancement": t["avancement_declare"], "echeance": ech.isoformat(),
         "est_en_retard": False, "jours_retard": 0, "jours_restants": None, "retard_final": None,
         # Avancement déclaré et statut sont INDÉPENDANTS : 100 % ne ferme jamais un ticket, la clôture attend la décision du responsable.
         "cloture_a_valider": t["statut"] != "ferme" and t["avancement_declare"] >= 100}
    if t["statut"] == "ferme":
        fin = dt.date.fromisoformat(str(t["date_fermeture"])) if t.get("date_fermeture") else today
        n = bd_between(ech, fin, holidays) if fin > ech else 0
        r.update(retard_final=n, situation="ferme",
                 libelle=f"Fermé (retard final : {_j(n)})" if n else "Fermé dans les délais")
        return r
    if today > ech or (today == ech and now.time() >= work_end):
        n = bd_between(ech, today, holidays)
        if t["statut"] == "en_attente":
            lib = f"En attente, échéance dépassée de {_j(n)}" if n else "En attente, échéance dépassée"
        else:
            lib = (f"En retard de {_j(n)}" if n else "Échéance dépassée aujourd'hui" if today == ech
                   else "Échéance dépassée (jour non ouvré)")
        r.update(est_en_retard=True, jours_retard=n, situation="en_retard", libelle=lib)
        return r
    restants = bd_between(today, ech, holidays)
    r["jours_restants"] = restants
    if restants <= seuil_jours and t["avancement_declare"] <= seuil_av:
        quand = "aujourd'hui" if restants == 0 else "demain" if restants == 1 else f"dans {_j(restants)}"
        r.update(situation="a_surveiller", libelle=f"À surveiller (échéance {quand})")
    else:
        r.update(situation="normale", libelle=f"Échéance dans {_j(restants)}")
    return r


def history_facts(hist: dict) -> dict:
    """Faits chiffrés tirés de l'historique CRM (nombre de blocages, motifs successifs)."""
    attentes = [h for h in hist["statuts"] if h["type_motif"] == "attente"]
    retards = [h for h in hist["statuts"] if h["type_motif"] == "retard"]
    return {
        "nb_blocages": len(attentes),
        "motifs_attente": [{"motif": h["motif"], "date": str(h["date"])[:10],
                            "resolu": bool(h["date_resolution"])} for h in attentes],
        "motifs_retard": [{"motif": h["motif"], "date": str(h["date"])[:10]} for h in retards],
        "avancements": [{"de": a["ancienne"], "a": a["nouvelle"], "date": str(a["date"])[:10]}
                        for a in hist["avancements"]],
    }


# ---------- Contrôles de conformité des textes de l'agent ----------
NUM = re.compile(r"\d+")


def numbers_in(text: str) -> set[int]:
    return {int(x) for x in NUM.findall(text)}


def check_recommendation(text: str, ticket_id: int, allowed: set[int]) -> list[str]:
    """Format imposé, vocabulaire, fidélité aux chiffres de Python."""
    errs, low = [], text.lower()
    if not text.startswith(f"T-{ticket_id:03d} :"):
        errs.append(f"Doit commencer par « T-{ticket_id:03d} : »")
    if len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]) > 3:
        errs.append("Trop long : constat chiffré, analyse, action (courtes phrases)")
    if "relanc" in low:
        errs.append("Le terme « relance » est interdit")
    if "ne progresse pas" in low:
        errs.append("Écrire « l'avancement déclaré est de X % », jamais « ne progresse pas »")
    inconnus = numbers_in(text) - allowed
    if inconnus:
        errs.append(f"Chiffres absents des résultats Python : {sorted(inconnus)}")
    return errs


def _choix(options: list[str], graine: int) -> str:
    """Choisit une formulation de façon stable (même ticket, même état → même texte) mais variée d'un ticket à l'autre."""
    return options[graine % len(options)]


def recommendation_fallback(t: dict, tr: dict, motif: str | None, ctx: dict | None = None) -> tuple[str, str] | None:
    """Recommandation déterministe (si le LLM est indisponible ou non conforme). Elle s'adapte à la situation réelle du ticket :
    ampleur du retard, avancement déclaré, tâches bloquées en aval, mises en attente répétées, proximité de l'échéance.
    Trois phrases au plus : constat chiffré, analyse, action. Tous les chiffres viennent de Python."""
    ctx = ctx or {}
    tid = f"T-{t['id']:03d}"
    av = tr["avancement"]
    nb_bloque = int(ctx.get("bloque") or 0)
    nb_att = int(ctx.get("nb_blocages") or 0)
    g = t["id"] + av
    aval = f"{nb_bloque} tâche{'s' if nb_bloque > 1 else ''} en aval" if nb_bloque else ""

    if tr.get("cloture_a_valider") and t["statut"] != "ferme":
        # Avancement déclaré à 100 % : le ticket garde son statut tant que le haut responsable n'a pas décidé de le clôturer.
        n = tr["jours_retard"]
        retard = (f", échéance dépassée de {_j(n)}" if n else ", échéance dépassée") if tr["situation"] == "en_retard" else ""
        fin = f" Elle retient {aval} : la clôture les débloquerait." if nb_bloque else ""
        return (f"{tid} : avancement déclaré {av} %, mais le ticket n'est pas fermé{retard}. "
                f"Le statut « {STATUT_LIB.get(t['statut'], t['statut'])} » est conservé tant que la clôture n'est pas validée.{fin} "
                "Il est recommandé d'examiner le ticket et de valider sa clôture si le travail est terminé.", "historique")

    if tr["situation"] == "en_retard":
        n = tr["jours_retard"]
        retard = f"en retard de {_j(n)}" if n else "échéance dépassée aujourd'hui"
        if nb_bloque:
            return (f"{tid} : {retard}, avancement déclaré {av} %, et elle retient {aval}. "
                    + _choix(["Chaque jour de plus décale directement ces tâches. Il est recommandé d'obtenir du membre une date de livraison ferme et d'arbitrer une réduction de périmètre si elle n'est pas tenable.",
                              "Le retard se propage au reste du planning. Il est recommandé de traiter cette tâche avant les autres retards et de demander un engagement de date au membre."], g),
                    "impact_systemique")
        if nb_att >= 2:
            return (f"{tid} : {retard}, après {nb_att} mises en attente successives. "
                    "Le blocage revient : le problème n'est probablement pas ponctuel. "
                    "Il est recommandé d'identifier avec le membre la cause de fond plutôt que de relever chaque blocage séparément.", "historique")
        if not motif:
            return (f"{tid} : {retard}, sans motif documenté (avancement déclaré {av} %). "
                    + _choix(["Faute d'explication, le retard ne peut être ni qualifié ni anticipé. Il est recommandé de demander au membre d'en préciser la cause avant toute décision.",
                              "Ce silence limite le pilotage. Il est recommandé d'obtenir du membre la cause du retard et une nouvelle date prévisionnelle."], g),
                    "manque_de_visibilite")
        if av >= 75:
            return (f"{tid} : {retard}, mais déjà avancée à {av} %. Le reste à faire est court (motif : « {motif} »). "
                    "Il est recommandé de demander au membre une date de clôture précise plutôt que de replanifier.", "historique")
        if av <= 25:
            return (f"{tid} : {retard} pour un avancement déclaré de {av} % (motif : « {motif} »). "
                    "L'écart entre le temps écoulé et le travail déclaré est important. "
                    "Il est recommandé de vérifier si la durée estimée est réaliste et, au besoin, de replanifier l'échéance ou de renforcer l'équipe.", "historique")
        return (f"{tid} : {retard}, avancement déclaré {av} %, motif « {motif} ». "
                + _choix(["Il est recommandé de vérifier que ce motif est toujours d'actualité et d'obtenir une nouvelle date d'engagement.",
                          "Il est recommandé d'examiner avec le membre ce qui reste à lever et de fixer une échéance révisée."], g),
                "historique")

    if tr["situation"] == "a_surveiller":
        r = tr["jours_restants"]
        quand = "aujourd'hui" if r == 0 else "demain" if r == 1 else f"dans {_j(r)}"
        fin = f", et elle retient {aval}" if nb_bloque else ""
        if av == 0:
            return (f"{tid} : échéance {quand}, tâche pas encore démarrée (avancement déclaré 0 %){fin}. "
                    + _choix(["Le délai restant est très court au regard du travail à fournir. Il est recommandé de confirmer dès maintenant que le membre est disponible.",
                              "Sans démarrage, l'échéance a peu de chances d'être tenue. Il est recommandé de vérifier ce qui empêche de commencer."], g),
                    "manque_de_visibilite")
        if av < 50:
            return (f"{tid} : échéance {quand} pour un avancement déclaré de {av} %{fin}. "
                    "Le rythme actuel ne suffit probablement pas. "
                    + _choix(["Il est recommandé d'anticiper un renfort ou un report plutôt que de constater le retard.",
                              "Il est recommandé de demander au membre s'il juge l'échéance tenable et d'arbitrer à l'avance."], g), "historique")
        return (f"{tid} : échéance {quand}, avancement déclaré {av} %{fin}. "
                "La tâche est bien engagée. "
                + _choix(["Il est recommandé de confirmer simplement la date de clôture prévue.",
                          "Il est recommandé de vérifier qu'aucun point résiduel ne risque de faire glisser la livraison."], g), "historique")

    if t["statut"] == "en_attente":
        rep = f" ({nb_att} mises en attente au total)" if nb_att >= 2 else ""
        return (f"{tid} : en attente, motif « {motif or 'non précisé'} »{rep}. "
                "Tant que la contrainte n'est pas levée, l'échéance se rapproche sans que la tâche avance. "
                "Il est recommandé d'identifier qui peut lever ce blocage et de lui fixer une date.", "historique")

    restants = tr.get("jours_restants")
    if restants is not None and restants <= 5 and t["statut"] != "ferme":
        quand = "aujourd'hui" if restants == 0 else "demain" if restants == 1 else f"dans {_j(restants)}"
        if t["statut"] in ("nouveau", "ouvert") and av == 0:
            return (f"{tid} : échéance {quand}, tâche pas encore démarrée (avancement déclaré 0 %). "
                    + _choix(["Il est recommandé de vérifier que le travail a bien commencé.",
                              "Il est recommandé de confirmer qui la prend en charge et à quelle date."], g), "manque_de_visibilite")
        return (f"{tid} : échéance {quand}, avancement déclaré {av} %. "
                "Il est recommandé de confirmer que le rythme permet de tenir l'échéance.", "historique")
    return None


# ---------- Priorisation déterministe pour la synthèse dynamique ----------
def blocked_map(tickets: dict[int, dict]) -> dict[int, list[int]]:
    """Pour chaque ticket du projet : tickets non fermés qui en dépendent (même projet uniquement)."""
    res: dict[int, list[int]] = {i: [] for i in tickets}
    for j, o in tickets.items():
        if o["statut"] == "ferme":
            continue
        for d in o.get("depend_de_ids") or []:
            if d in res:
                res[d].append(j)
    return res


def prioritize(tickets: dict[int, dict], tracking: dict[int, dict], blocks: dict[int, list[int]],
               nb_blocages: dict[int, int] | None = None, limit: int = 5) -> list[dict]:
    """Ordre des tâches qui appellent l'attention du haut responsable (règles simples, sans scoring complexe) :
    retard avant « à surveiller » avant attente ; puis tâches qui en bloquent d'autres, retard sans motif,
    blocages répétés, jours de retard, faible avancement. Tous les chiffres viennent de Python."""
    nb_blocages = nb_blocages or {}
    cand = []
    for i, tr in tracking.items():
        t = tickets[i]
        if tr["situation"] == "en_retard":
            cat = 0
        elif tr["situation"] == "a_surveiller":
            cat = 1
        elif t["statut"] == "en_attente":
            cat = 2
        else:
            continue
        motif = t.get("motif_retard_courant") or t.get("motif_attente_courant")
        raisons = []
        if tr["situation"] == "en_retard":
            raisons.append(f"retard de {_j(tr['jours_retard'])}" if tr["jours_retard"] else "échéance dépassée")
        elif tr["situation"] == "a_surveiller":
            raisons.append(f"échéance dans {_j(tr['jours_restants'])}, avancement déclaré {tr['avancement']} %")
        else:
            raisons.append("en attente")
        nb = len(blocks.get(i, []))
        if nb:
            raisons.append(f"bloque {nb} tâche{'s' if nb > 1 else ''}")
        if tr["situation"] == "en_retard" and not motif:
            raisons.append("aucun motif documenté")
        if nb_blocages.get(i, 0) > 1:
            raisons.append(f"{nb_blocages[i]} mises en attente successives")
        key = (cat, -nb, 0 if (cat == 0 and not motif) else 1, -nb_blocages.get(i, 0), -tr["jours_retard"],
               tr["avancement"], i)
        cand.append((key, {"id": i, "situation": tr["situation"], "raisons": raisons, "nb_bloquees": nb,
                           "bloque": blocks.get(i, []), "motif": motif}))
    cand.sort(key=lambda x: x[0])
    return [{"rang": r + 1, **c} for r, (_, c) in enumerate(cand[:limit])]