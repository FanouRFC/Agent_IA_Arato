"""Connecteur CRM : SEUL accès au CRM. Appelé par le backend, jamais par l'agent IA."""
import datetime as dt

import httpx

from .config import settings


class CrmConnector:
    def __init__(self):
        self.c = httpx.Client(base_url=settings.crm_url, timeout=20,
                              headers={"X-Service-Key": settings.crm_service_key})

    def _get(self, path, **params):
        r = self.c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def _put(self, path, body):
        r = self.c.put(path, json=body)
        r.raise_for_status()
        return r.json()

    # Lecture
    def list_tickets(self, **filters): return self._get("/tickets", **filters)
    def get_ticket(self, tid): return self._get(f"/tickets/{tid}")
    def historique(self, tid): return self._get(f"/tickets/{tid}/historique")
    def membres_du_ticket(self, tid): return self._get(f"/tickets/{tid}/membres")
    def membres(self): return self._get("/membres")
    def profils(self): return self._get("/profils")
    def projets(self): return self._get("/projets")
    def evenements(self, since_id=0): return self._get("/evenements", since_id=since_id)

    # Écriture (uniquement après validation humaine, ou indicateur calculé par Python)
    def create_ticket(self, payload: dict):
        r = self.c.post("/tickets", json=payload)
        r.raise_for_status()
        return r.json()

    def set_echeance(self, tid: int, d: dt.date): return self._put(f"/tickets/{tid}/echeance", {"echeance": str(d)})
    def set_est_en_retard(self, tid: int, v: bool): return self._put(f"/tickets/{tid}/est-en-retard", {"valeur": v})


connector = CrmConnector()
