"""Client LLM (API compatible OpenAI). Le fournisseur est un simple paramètre de configuration (.env).

Conçu pour les API en ligne : limitation de débit, nouvelles tentatives sur 429/5xx (en respectant Retry-After),
erreurs explicites. La clé d'API se configure uniquement dans le fichier .env du serveur ; elle n'est jamais
journalisée, jamais renvoyée à l'interface et jamais citée dans un message d'erreur."""
import logging
import re
import threading
import time
from urllib.parse import urlparse

import httpx

from . import settings_store
from .config import settings
from .db import SessionLocal

log = logging.getLogger("llm")
_throttle = threading.Lock()
_last_call = 0.0


class LLMError(Exception):
    """Fournisseur indisponible, quota dépassé, accès refusé…"""


# Vocabulaire de l'interface : le mot « ouvré(s) » n'est jamais affiché (« 5 jours », et non « 5 jours ouvrés »).
_OUVRES = re.compile(r"\s+ouvré(?:e)?s?\b", re.IGNORECASE)
# Modèles qui ne produisent pas de texte (voix, modération, vecteurs…) : inutiles pour l'agent.
_NON_TEXTE = re.compile(r"whisper|tts|speech|guard|moderation|embed|rerank|orpheus|playai|dall-e|image|vision-preview", re.IGNORECASE)


def _clean(msg: dict) -> dict:
    if isinstance(msg.get("content"), str):
        msg["content"] = _OUVRES.sub("", msg["content"])
    return msg


def _ensure_configured():
    if not provider()["cle_configuree"]:
        raise LLMError("Le fournisseur d'IA n'est pas encore configuré sur le serveur : contactez l'administrateur système.")


def current_model() -> str:
    with SessionLocal() as db:
        return settings_store.params(db)["llm_model"]


def provider() -> dict:
    u = urlparse(settings.llm_base_url)
    host = u.hostname or ""
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
    return {"hote": host, "local": local, "cle_configuree": bool(settings.llm_api_key) or local,
            "ollama": local and (u.port == 11434 or "ollama" in host.lower())}


def fournisseur_cle() -> str:
    """Identifiant du fournisseur configuré (hôte:port) : un modèle choisi dans l'administration ne vaut que pour lui."""
    u = urlparse(settings.llm_base_url)
    return f"{u.hostname or ''}:{u.port or ''}".lower()


def _serveur_local_injoignable() -> str:
    u = urlparse(settings.llm_base_url)
    cible = f"{u.hostname}:{u.port}" if u.port else (u.hostname or "?")
    return (f"le serveur de modèle local ({cible}) est injoignable : démarrez-le (Ollama : « ollama serve ») "
            "et vérifiez LLM_BASE_URL dans .env")


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.llm_api_key or 'none'}", "Content-Type": "application/json"}


def _wait_turn():
    """Espace les appels : les offres gratuites imposent un nombre de requêtes par minute (inutile en local)."""
    global _last_call
    if provider()["local"]:
        return
    with _throttle:
        delta = time.monotonic() - _last_call
        if delta < settings.llm_min_interval:
            time.sleep(settings.llm_min_interval - delta)
        _last_call = time.monotonic()


def _retry_delay(r: httpx.Response | None, attempt: int) -> float:
    if r is not None:
        ra = r.headers.get("retry-after")
        if ra and ra.replace(".", "", 1).isdigit():
            return min(float(ra) + 0.5, 60)
        m = re.search(r"try again in ([\d.]+)\s*(ms|s)", r.text or "")
        if m:
            v = float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
            return min(v + 0.5, 60)
    return min(2 ** attempt * 2, 30)


def _explain(r: httpx.Response) -> str:
    if r.status_code in (401, 403):
        return "Accès refusé par le fournisseur d'IA."

    if r.status_code == 404:
        return "Modèle introuvable chez le fournisseur."

    if r.status_code == 429:
        log.error(
            "ERREUR LLM 429 - Réponse fournisseur : %s",
            (r.text or "")[:2000]
        )
        return "Limite de requêtes atteinte. Consultez les logs du serveur."

    return f"HTTP {r.status_code} : {(r.text or '')[:300]}"


def chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2,
         max_tokens: int | None = None, json_mode: bool = False) -> dict:
    _ensure_configured()
    payload: dict = {"model": current_model(), "messages": messages, "temperature": temperature}
    if tools:
        payload["tools"] = tools
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    local = provider()["local"]
    # En local, relancer une génération trop longue ne ferait que la rallonger : au plus un nouvel essai, jamais sur délai dépassé.
    retries = min(1, settings.llm_max_retries) if local else settings.llm_max_retries
    last = "aucune réponse"
    sans_outils = False
    attempt = 0
    while True:
        _wait_turn()
        r = None
        t0 = time.monotonic()
        try:
            r = httpx.post(url, json=payload, headers=_headers(), timeout=settings.llm_timeout)
        except httpx.TimeoutException:
            last = f"délai dépassé ({settings.llm_timeout} s) : le modèle est trop lent pour cette demande"
            if local:
                raise LLMError(last)
        except httpx.TransportError as e:
            last = _serveur_local_injoignable() if local else f"connexion impossible ({type(e).__name__})"
            if local:
                raise LLMError(last)             # inutile de réessayer : le serveur local n'est pas démarré
        else:
            if r.status_code == 200:
                try:
                    data = r.json()
                    log.info("LLM %s : %.1f s · %s", payload["model"], time.monotonic() - t0, data.get("usage") or "")
                    return _clean(data["choices"][0]["message"])
                except (KeyError, IndexError, ValueError):
                    last = "réponse du fournisseur illisible"
            elif (r.status_code == 400 and tools and not sans_outils and re.search(r"does not support tools|tools? (?:are )?not supported", r.text or "", re.I)):
                # Modèle local sans appel d'outils (certains modèles Ollama) : on redemande sans « tools » ; l'agent lit alors le JSON du texte.
                log.warning("Le modèle %s ne gère pas les appels d'outils : nouvelle tentative en mode texte/JSON", payload["model"])
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
                sans_outils = True
                continue                                        # redemande aussitôt, sans consommer un essai
            elif r.status_code in (429, 500, 502, 503, 504) or (r.status_code == 400 and "tool_use_failed" in r.text):
                last = _explain(r)
            else:
                raise LLMError(_explain(r))
        if attempt >= retries:
            break
        d = _retry_delay(r, attempt)
        log.warning("LLM : %s — nouvel essai dans %.1f s", last, d)
        time.sleep(d)
        attempt += 1
    raise LLMError(last)


def list_models() -> list[str]:
    _ensure_configured()
    local = provider()["local"]
    try:
        r = httpx.get(settings.llm_base_url.rstrip("/") + "/models", headers=_headers(), timeout=20)
        if local and r.status_code == 404:           # serveur local sans /v1/models : liste native d'Ollama (/api/tags)
            racine = urlparse(settings.llm_base_url)
            r = httpx.get(f"{racine.scheme}://{racine.netloc}/api/tags", headers=_headers(), timeout=20)
    except httpx.HTTPError as e:
        raise LLMError(_serveur_local_injoignable() if local else f"connexion impossible ({type(e).__name__})")
    if r.status_code != 200:
        raise LLMError(_explain(r))
    try:
        corps = r.json()
        data = corps.get("data") or corps.get("models") or []
        ids = [(m.get("id") or m.get("name") or m.get("model") or "").removeprefix("models/") for m in data if isinstance(m, dict)]
    except ValueError:
        raise LLMError("liste des modèles illisible")
    return sorted(i for i in ids if i and not _NON_TEXTE.search(i))


def _meme_modele(voulu: str, installe: str) -> bool:
    """« llama3.1 » désigne « llama3.1:latest » chez Ollama."""
    return installe == voulu or installe == f"{voulu}:latest" or voulu == f"{installe}:latest"


def verifier() -> dict:
    """Vérification complète du fournisseur d'IA, étape par étape : joignable → modèle configuré disponible → génération réelle."""
    etapes = []
    modeles = list_models()                      # LLMError explicite si le serveur est arrêté ou la clé refusée
    etapes.append({"etape": "serveur", "ok": True, "detail": f"{len(modeles)} modèle(s) proposé(s)"})
    voulu = current_model()
    if modeles and not any(_meme_modele(voulu, m) for m in modeles):
        indice = f" (Ollama : « ollama pull {voulu} »)" if provider()["local"] else ""
        raise LLMError(f"le modèle « {voulu} » n'est pas disponible chez ce fournisseur{indice}. Disponibles : "
                       + ", ".join(modeles[:8]) + ("…" if len(modeles) > 8 else ""))
    etapes.append({"etape": "modele", "ok": True, "detail": voulu})
    res = ping()
    etapes.append({"etape": "generation", "ok": True, "detail": f"{res['latence_ms']} ms"})
    return {**res, "etapes": etapes, "local": provider()["local"]}


def ping() -> dict:
    t0 = time.monotonic()
    msg = chat([{"role": "user", "content": "Réponds uniquement : OK"}], max_tokens=10)
    return {"ok": True, "latence_ms": int((time.monotonic() - t0) * 1000), "modele": current_model(),
            "reponse": (msg.get("content") or "").strip()[:40]}
