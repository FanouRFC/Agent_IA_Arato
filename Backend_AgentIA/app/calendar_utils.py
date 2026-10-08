"""Jours ouvrés (lundi-vendredi hors jours fériés configurables)."""
import datetime as dt


def is_bd(d: dt.date, holidays) -> bool:
    return d.weekday() < 5 and d not in holidays


def add_bd(d: dt.date, n: int, holidays=frozenset()) -> dt.date:
    step, k = (1 if n >= 0 else -1), abs(n)
    while k:
        d += dt.timedelta(days=step)
        if is_bd(d, holidays):
            k -= 1
    return d


def bd_between(start: dt.date, end: dt.date, holidays=frozenset()) -> int:
    """Nombre de jours ouvrés dans l'intervalle ]start, end]."""
    n, d = 0, start
    while d < end:
        d += dt.timedelta(days=1)
        n += is_bd(d, holidays)
    return n
