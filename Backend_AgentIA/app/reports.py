"""Rapports PDF (reportlab) et Excel (openpyxl) pour UN projet : sobres, à l'en-tête d'Arato, quatre teintes + un accent.

Logo : si le fichier `app/assets/logo_arato.png` existe, il est utilisé tel quel (en-tête de chaque page) ; sinon une marque
vectorielle « arato » est dessinée. Remplacer le fichier suffit pour changer le logo, sans toucher au code."""
import datetime as dt
import html
import io
import logging
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak

log = logging.getLogger("rapports")
INK, MID, STEEL, GREY, PALE, ACCENT = "#082032", "#2C394B", "#334756", "#D2D2D2", "#F4F5F6", "#FF4C29"
STATUT = {"nouveau": "Nouveau", "ouvert": "Ouvert", "en_cours": "En cours", "en_attente": "En attente", "ferme": "Fermé"}
HEAD = ["Ticket", "Titre", "Équipe", "Statut", "Avanc.", "Échéance / situation", "Motif documenté"]
PAGE_W, PAGE_H = A4
MX = 18 * mm
LOGO = Path(__file__).parent / "assets" / "logo_arato.png"
_FONTS = Path(__file__).parent / "fonts"
_F = {"r": "Helvetica", "l": "Helvetica", "m": "Helvetica-Bold", "b": "Helvetica-Bold"}   # repli si Poppins est illisible
_ok = False


def _fonts():
    """Poppins est embarquée dans le dépôt : rendu identique partout. Au pire, Helvetica prend le relais (jamais d'échec)."""
    global _ok
    if _ok:
        return
    try:
        for nom, f in (("Poppins", "Regular"), ("Poppins-Light", "Light"), ("Poppins-Medium", "Medium"), ("Poppins-Bold", "Bold")):
            pdfmetrics.registerFont(TTFont(nom, str(_FONTS / f"Poppins-{f}.ttf")))
        pdfmetrics.registerFontFamily("Poppins", normal="Poppins", bold="Poppins-Bold", italic="Poppins", boldItalic="Poppins-Bold")
        _F.update(r="Poppins", l="Poppins-Light", m="Poppins-Medium", b="Poppins-Bold")
    except Exception:
        pass
    _ok = True


# Caractères de contrôle (tabulation verticale, saut de page, NUL…) : fréquents dans le texte extrait d'un PDF ou d'un document Word,
# invisibles, mais refusés par le format Excel (openpyxl lève IllegalCharacterError) et sans sens dans un PDF.
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]")


def propre(x) -> str:
    """Texte sûr pour un rapport : jamais None, sans caractère de contrôle, retours à la ligne normalisés."""
    return _CONTROLE.sub("", str(x if x is not None else "")).replace("\r\n", "\n").replace("\r", "\n")


def esc(x) -> str:
    """Tout texte venant des données est nettoyé et échappé : un « & », un « < » ou un caractère de contrôle dans un titre
    ne peut plus casser le PDF."""
    return html.escape(propre(x), quote=False)


def _cellule(v):
    """Valeur sûre pour une cellule Excel : texte nettoyé, limité à 32 000 caractères (maximum d'Excel : 32 767)."""
    if isinstance(v, str):
        return propre(v)[:32000]
    return v


def _ecrire(ws, ligne: int, col: int, v):
    """Écrit une cellule ; un texte qui commence par « = » reste du TEXTE (jamais interprété comme une formule)."""
    c = ws.cell(ligne, col, _cellule(v))
    if isinstance(c.value, str) and c.value.startswith("="):
        c.data_type = "s"
    return c


def _heure(iso) -> str:
    try:
        return f"{dt.datetime.fromisoformat(str(iso)):%d/%m %H:%M}"
    except (ValueError, TypeError):
        return ""


def _rows(tickets, tracking, noms=None):
    noms = noms or {}
    return [[f"T-{i:03d}", t["titre"], ", ".join(noms.get(m, "?") for m in t.get("membre_ids", [])) or "—",
             STATUT.get(t["statut"], t["statut"]), f"{100 if t['statut'] == 'ferme' else t['avancement_declare']} %",
             tracking[i]["libelle"], t.get("motif_retard_courant") or t.get("motif_attente_courant") or "—"]
            for i, t in tickets.items()]


def _logo(c, x, y, h):
    """Logo d'Arato (hauteur h, coin bas-gauche en x, y). Retourne sa largeur."""
    if LOGO.exists():
        try:
            img = ImageReader(str(LOGO))
            iw, ih = img.getSize()
            w = h * iw / ih
            c.drawImage(img, x, y, width=w, height=h, mask="auto")
            return w
        except Exception:
            pass
    c.setFillColor(colors.HexColor(INK)); c.roundRect(x, y, h, h, h * 0.26, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont(_F["b"], h * 0.80); c.drawCentredString(x + h / 2, y + h * 0.2, "a")
    c.setFillColor(colors.HexColor(ACCENT)); c.circle(x + h * 0.81, y + h * 0.80, h * 0.075, fill=1, stroke=0)
    c.setFillColor(colors.HexColor(INK)); c.setFont(_F["b"], h * 0.70); c.drawString(x + h * 1.3, y + h * 0.2, "arato")
    return h * 1.3 + pdfmetrics.stringWidth("arato", _F["b"], h * 0.70)


def _decor(canv, doc):
    """En-tête (logo, titre du document) et pied de page (date, pagination) de chaque page."""
    m, w, h = doc.meta, PAGE_W, PAGE_H
    canv.saveState()
    _logo(canv, MX, h - 19 * mm, 8 * mm)
    canv.setFillColor(colors.HexColor(STEEL)); canv.setFont(_F["m"], 8.5)
    canv.drawRightString(w - MX, h - 14.3 * mm, "Rapport de suivi de projet")
    canv.setFont(_F["r"], 7.5); canv.setFillColor(colors.HexColor("#5E6D7C"))
    canv.drawRightString(w - MX, h - 18.3 * mm, m["projet"][:80])
    canv.setStrokeColor(colors.HexColor(GREY)); canv.setLineWidth(0.6); canv.line(MX, h - 22.5 * mm, w - MX, h - 22.5 * mm)
    canv.line(MX, 15 * mm, w - MX, 15 * mm)
    canv.setFont(_F["r"], 7.5)
    canv.drawString(MX, 10.5 * mm, f"Arato · Rapport généré le {m['date']}")
    canv.drawRightString(w - MX, 10.5 * mm, f"Page {doc.page}" + (f" / {doc.total}" if doc.total else ""))
    canv.restoreState()


class _Bar(Flowable):
    """Barre de progression fine : piste grise, remplissage bleu nuit."""
    def __init__(self, pct, width):
        super().__init__(); self.pct, self.width, self.height = max(0, min(100, pct)), width, 2.2 * mm

    def draw(self):
        c = self.canv
        c.setFillColor(colors.HexColor(GREY)); c.roundRect(0, 0, self.width, self.height, self.height / 2, fill=1, stroke=0)
        if self.pct:
            c.setFillColor(colors.HexColor(INK)); c.roundRect(0, 0, max(self.height, self.width * self.pct / 100), self.height, self.height / 2, fill=1, stroke=0)


class _Dist(Flowable):
    """Barre de répartition empilée (une teinte par situation) : lecture immédiate de la santé du projet."""
    def __init__(self, parts, width):
        super().__init__(); self.parts, self.width, self.height = [p for p in parts if p[1] > 0], width, 3.6 * mm

    def draw(self):
        c, total, x = self.canv, sum(p[1] for p in self.parts) or 1, 0
        for k, (_, n, col) in enumerate(self.parts):
            w = self.width * n / total
            c.setFillColor(colors.HexColor(col))
            c.roundRect(x, 0, max(w - 0.8 * mm, 1), self.height, 1.4 * mm, fill=1, stroke=0)
            x += w


def _charge(tickets, tracking, noms):
    """Charge par membre : tickets non fermés, retards, avancement déclaré moyen."""
    m: dict[int, dict] = {}
    for i, t in tickets.items():
        if t["statut"] == "ferme":
            continue
        for mid in t.get("membre_ids") or []:
            x = m.setdefault(mid, {"nom": (noms or {}).get(mid, "?"), "n": 0, "late": 0, "av": 0})
            x["n"] += 1
            x["late"] += tracking[i]["situation"] == "en_retard"
            x["av"] += t["avancement_declare"]
    out = sorted(m.values(), key=lambda x: (-x["late"], -x["n"]))
    for x in out:
        x["moy"] = round(x["av"] / x["n"]) if x["n"] else 0
    return out


def _build(story_fn, meta: dict, total: int) -> tuple[bytes, int]:
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MX, rightMargin=MX, topMargin=28 * mm, bottomMargin=20 * mm,
                          title=f"Rapport de suivi – {meta['projet']}", author="Arato", subject="Rapport de suivi de projet")
    doc.meta, doc.total = meta, total
    frame = Frame(MX, 20 * mm, PAGE_W - 2 * MX, PAGE_H - 48 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate("p", [frame], onPage=_decor)])
    doc.build(story_fn())
    return buf.getvalue(), doc.page


def pdf(projet: str, synthese: str, tickets, tracking, stats, recos, en_clair=None, noms=None,
        priorites=None, risques=None, evolutions=None) -> bytes:
    _fonts()
    meta = {"projet": projet, "date": f"{dt.datetime.now():%d/%m/%Y à %H:%M}"}
    W = PAGE_W - 2 * MX
    P = lambda n, **k: ParagraphStyle(n, fontName=k.pop("font", _F["r"]), **k)
    corps = P("corps", fontSize=9.5, leading=15, textColor=colors.HexColor(MID), spaceAfter=4)
    cell = P("cell", fontSize=7.8, leading=10.4, textColor=colors.HexColor(MID))
    cellb = P("cellb", font=_F["m"], fontSize=7.8, leading=10.4, textColor=colors.HexColor(INK))
    celh = P("celh", font=_F["m"], fontSize=7.4, leading=9.6, textColor=colors.white)
    petit = P("petit", fontSize=7.8, leading=11, textColor=colors.HexColor("#5E6D7C"))
    h2 = P("h2", font=_F["b"], fontSize=12, leading=15, textColor=colors.HexColor(INK))
    ec = en_clair or {}

    compteur = [0]

    def titre(t):
        compteur[0] += 1
        tb = Table([[Paragraph(f'<font color="{ACCENT}">{compteur[0]:02d}</font>&nbsp;&nbsp;{esc(t)}', h2)]], colWidths=[W])
        tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor(GREY)), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        tb.keepWithNext = True
        return [CondPageBreak(42 * mm), Spacer(1, 7 * mm), tb, Spacer(1, 3 * mm)]

    def liste(rows, widths, extra=()):
        tb = Table(rows, colWidths=widths)
        tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(GREY)),
                                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 4), *extra]))
        return tb

    def story():
        compteur[0] = 0
        f = []
        # --- Titre du rapport ---
        f += [Spacer(1, 2 * mm),
              Paragraph("RAPPORT DE SUIVI DE PROJET", P("e", font=_F["m"], fontSize=8, leading=11, textColor=colors.HexColor("#5E6D7C"))),
              Spacer(1, 1.5 * mm),
              Paragraph(esc(projet), P("t", font=_F["b"], fontSize=22, leading=27, textColor=colors.HexColor(INK))),
              Spacer(1, 1.5 * mm),
              Paragraph(f"Situation au {meta['date']} · Document à usage interne", P("s", fontSize=9, leading=12, textColor=colors.HexColor(STEEL))),
              Spacer(1, 3 * mm)]
        bar = Table([[""]], colWidths=[18 * mm], rowHeights=[1.2 * mm])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(ACCENT))])); bar.hAlign = "LEFT"
        f += [bar, Spacer(1, 7 * mm)]

        # --- Chiffres clés : colonnes séparées par un filet, sans fond ---
        cles = [(stats["total"], "tickets", INK), (stats["en_retard"], "en retard", ACCENT if stats["en_retard"] else INK),
                (stats["a_surveiller"], "à surveiller", INK), (stats["par_statut"]["en_attente"], "en attente", INK),
                (stats["par_statut"]["ferme"], "fermés", INK)]
        if ec:
            cles.append((f"{ec.get('progression', 0)} %", "d'avancement", INK))
        n = len(cles)
        kpi = Table([[Paragraph(f'<font name="{_F["b"]}" size="19" color="{c}">{v}</font>', P("k", alignment=1, leading=24)) for v, _, c in cles],
                     [Paragraph(esc(l), P("kl", alignment=1, fontSize=7.8, leading=10, textColor=colors.HexColor("#5E6D7C"))) for _, l, _ in cles]],
                    colWidths=[W / n] * n)
        kpi.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor(GREY)), ("LINEBELOW", (0, -1), (-1, -1), 0.6, colors.HexColor(GREY)),
                                 ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.HexColor(GREY)), ("TOPPADDING", (0, 0), (-1, 0), 9),
                                 ("BOTTOMPADDING", (0, 0), (-1, 0), 0), ("TOPPADDING", (0, 1), (-1, 1), 1), ("BOTTOMPADDING", (0, 1), (-1, 1), 9)]))
        f.append(kpi)
        autres = stats["total"] - stats["en_retard"] - stats["a_surveiller"] - stats["par_statut"]["ferme"]
        sain = round(100 * (stats["total"] - stats["en_retard"] - stats["a_surveiller"]) / stats["total"]) if stats["total"] else 100
        parts = [("En retard", stats["en_retard"], ACCENT), ("À surveiller", stats["a_surveiller"], "#FFB199"),
                 ("Dans les délais", max(0, autres), "#5E7C96"), ("Terminés", stats["par_statut"]["ferme"], "#9AA7B4")]
        leg = "   ".join(f'<font color="{c}">●</font> {l} {n}' for l, n, c in parts if n)
        f += [Spacer(1, 4 * mm), _Dist(parts, W), Spacer(1, 2 * mm),
              Paragraph(f"{leg}   ·   <font name=\"{_F['b']}\" color=\"{INK}\">{sain} %</font> des tickets sans alerte", petit)]

        # --- Situation générale ---
        if ec:
            f += titre("Situation générale")
            f += [Paragraph(f'<font name="{_F["b"]}" color="{INK}">{esc(ec.get("titre", ""))}</font>', P("v", fontSize=11, leading=15, spaceAfter=2)),
                  Paragraph(esc(ec.get("phrase", "")), corps), Spacer(1, 1 * mm), _Bar(ec.get("progression", 0), W), Spacer(1, 1.5 * mm),
                  Paragraph(f"{ec.get('progression', 0)} % du travail est fait", petit)]
            p = ec.get("prochaine")
            if p:
                try:
                    jour = f"{dt.date.fromisoformat(str(p['echeance'])[:10]):%d/%m/%Y}"
                except ValueError:
                    jour = str(p.get("echeance", ""))
                f.append(Paragraph(f'Prochaine échéance : <font name="{_F["m"]}" color="{INK}">T-{p["id"]:03d} · {esc(p.get("titre", ""))}</font>, le {jour}', petit))

        # --- Synthèse de l'agent ---
        lignes = [x.strip() for x in (synthese or "").split("\n") if x.strip()]
        if lignes:
            f += titre("Synthèse de l'agent") + [Paragraph(esc(x), corps) for x in lignes]

        # --- Priorités ---
        if priorites:
            rows = [[Paragraph(str(p.get("rang", k)), cellb),
                     [Paragraph(f'T-{p["id"]:03d} · {esc(p.get("titre", ""))}', cellb)] +
                     ([Paragraph(esc(" · ".join(p["raisons"])), cell)] if p.get("raisons") else [])] for k, p in enumerate(priorites[:8], 1)]
            f += titre("À traiter en priorité") + [liste(rows, [8 * mm, W - 8 * mm])]

        # --- Risques et prédictions ---
        if risques:
            rows = []
            for r in risques[:10]:
                haut = r.get("risque") == "eleve"
                niveau = f'<font name="{_F["m"]}" size="7.4" color="{ACCENT if haut else STEEL}">{"ÉLEVÉ" if haut else "MODÉRÉ"}</font>'
                rows.append([Paragraph(niveau, cell),
                             [Paragraph(f'T-{r["id"]:03d} · {esc(r.get("titre", ""))}', cellb)] +
                             ([Paragraph(esc(r["prediction"]), cell)] if r.get("prediction") else [])])
            f += titre("Risques et prédictions") + [liste(rows, [16 * mm, W - 16 * mm])]

        # --- Évolution depuis la dernière fois ---
        if evolutions:
            rows = [[Paragraph(esc(_heure(e.get("t"))), P("h", fontSize=7.4, leading=10, textColor=colors.HexColor("#5E6D7C"))), Paragraph(esc(e.get("txt", "")), cell)]
                    for e in evolutions[:15]]
            f += titre("Évolution depuis la dernière fois") + [liste(rows, [22 * mm, W - 22 * mm])]

        # --- Recommandations ---
        if recos:
            lib = {"suivie": "SUIVIE", "rejetee": "REJETÉE"}
            rows = [[Paragraph(f'<font name="{_F["m"]}" size="7" color="{STEEL}">{lib.get(dec or "", "À EXAMINER")}</font>', cell), Paragraph(esc(texte), cell)]
                    for texte, dec in recos[:12]]
            f += titre("Recommandations de l'agent") + [liste(rows, [20 * mm, W - 20 * mm])]

        # --- Charge de l'équipe ---
        ch = _charge(tickets, tracking, noms)
        if ch:
            rows = [[Paragraph(h, celh) for h in ("Membre", "Tickets en cours", "Dont en retard", "Avancement moyen")]]
            for x in ch[:10]:
                rows.append([Paragraph(f'<font name="{_F["m"]}">{esc(x["nom"])}</font>', cell), Paragraph(str(x["n"]), cell),
                             Paragraph(f'<font color="{ACCENT if x["late"] else MID}">{x["late"]}</font>', cell), Paragraph(f'{x["moy"]} %', cell)])
            tc = Table(rows, colWidths=[W * .4, W * .2, W * .2, W * .2])
            tc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)), ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(GREY)),
                                    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PALE)])]))
            f += titre("Charge de l'équipe") + [tc]

        # --- Tickets ---
        data = [[Paragraph(h, celh) for h in HEAD]]
        rows = _rows(tickets, tracking, noms)
        for r, i in zip(rows, tickets):
            retard = tracking[i]["situation"] == "en_retard"
            sit = f'<font name="{_F["m"]}" color="{ACCENT}">{esc(r[5])}</font>' if retard else esc(r[5])
            data.append([Paragraph(f'<font name="{_F["m"]}">{esc(r[0])}</font>', cell)] + [Paragraph(esc(c), cell) for c in r[1:5]] +
                        [Paragraph(sit, cell), Paragraph(esc(r[6]), cell)])
        cws = [13 * mm, 31 * mm, 23 * mm, 18 * mm, 14 * mm, 29 * mm]
        cws.append(W - sum(cws))
        tb = Table(data, repeatRows=1, colWidths=cws)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor(GREY)), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PALE)]),
                                *[("BACKGROUND", (0, k), (-1, k), colors.HexColor("#FFF3F0")) for k, i in enumerate(tickets, 1) if tracking[i]["situation"] == "en_retard"]]))
        f += titre("Tickets, équipe et motifs") + [tb, Spacer(1, 5 * mm),
              Paragraph("Les dates et retards sont calculés en jours ouvrés (week-ends et jours fériés exclus). "
                        "Les chiffres proviennent du CRM ; l'IA n'en calcule aucun.", petit)]
        return f

    try:
        _, pages = _build(story, meta, 0)            # 1re passe : compte les pages
        contenu, _ = _build(story, meta, pages)      # 2e passe : « Page X / N »
        return contenu
    except Exception:
        # Un contenu inattendu ne doit jamais empêcher d'obtenir le rapport : version simplifiée (texte seul, polices standard).
        log.exception("Mise en page complète du rapport impossible (projet %s) : version simplifiée", projet)
        return _pdf_simple(projet, synthese, tickets, tracking, stats, recos, priorites, risques, evolutions, noms)


def _pdf_simple(projet, synthese, tickets, tracking, stats, recos, priorites, risques, evolutions, noms) -> bytes:
    """Rapport de secours : mêmes informations, mise en page minimale (aucune police ni image externe, aucun tableau)."""
    from reportlab.platypus import SimpleDocTemplate
    st = ParagraphStyle("n", fontName="Helvetica", fontSize=9.5, leading=13)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=10)
    f = [Paragraph(esc(f"Rapport de suivi – {projet}"), ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=20)),
         Paragraph(f"Généré le {dt.datetime.now():%d/%m/%Y à %H:%M}", st), Spacer(1, 6),
         Paragraph(esc(f"{stats['total']} tickets · {stats['en_retard']} en retard · {stats['a_surveiller']} à surveiller · "
                       f"{stats['par_statut']['en_attente']} en attente · {stats['par_statut']['ferme']} fermés"), st)]
    def bloc(titre, lignes):
        if lignes:
            f.append(Paragraph(esc(titre), h))
            f.extend(Paragraph(esc(x), st) for x in lignes)
    bloc("Synthèse de l'agent", [x for x in (synthese or "").split("\n") if x.strip()])
    bloc("À traiter en priorité", [f"T-{p['id']:03d} · {p.get('titre', '')} : {' · '.join(p.get('raisons', []))}" for p in priorites or []])
    bloc("Risques et prédictions", [f"T-{r['id']:03d} · {r.get('titre', '')} : {r.get('prediction', '')}" for r in risques or []])
    bloc("Évolution", [f"{_heure(e.get('t'))} {e.get('txt', '')}" for e in (evolutions or [])[:15]])
    bloc("Recommandations", [t for t, _ in recos])
    bloc("Tickets", [" | ".join(str(c) for c in r) for r in _rows(tickets, tracking, noms)])
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=MX, rightMargin=MX, topMargin=18 * mm, bottomMargin=18 * mm).build(f)
    return buf.getvalue()


def xlsx(projet: str, synthese: str, tickets, tracking, stats, recos, en_clair=None, noms=None,
         priorites=None, risques=None, evolutions=None) -> bytes:
    wb = Workbook()
    thin = Side(style="thin", color="D2D2D2")
    entete = PatternFill("solid", fgColor="082032")
    retard = PatternFill("solid", fgColor="FFF3F0")
    blanc = Font(bold=True, color="FFFFFF")

    ws = wb.active
    ws.title = "Synthèse"
    ws["A1"], ws["A1"].font = "ARATO", Font(bold=True, size=11, color="FF4C29")
    _ecrire(ws, 2, 1, f"Rapport de suivi – {projet}").font = Font(bold=True, size=15, color="082032")
    ws["A3"], ws["A3"].font = f"Généré le {dt.datetime.now():%d/%m/%Y %H:%M}", Font(color="5E6D7C")
    chiffres = [("Tickets", stats["total"]), ("En retard", stats["en_retard"]), ("À surveiller", stats["a_surveiller"]),
                ("En attente", stats["par_statut"]["en_attente"]), ("Fermés", stats["par_statut"]["ferme"])]
    if en_clair:
        chiffres.append(("Avancement", f"{en_clair.get('progression', 0)} %"))
    for k, (lib, val) in enumerate(chiffres, 5):
        _ecrire(ws, k, 1, lib).font = Font(bold=True, color="334756")
        _ecrire(ws, k, 2, val).alignment = Alignment(horizontal="left")
    ligne = 5 + len(chiffres) + 1
    ws.cell(ligne, 1, "Synthèse de l'agent").font = Font(bold=True, size=12, color="082032")
    _ecrire(ws, ligne + 1, 1, synthese or "")
    ws.cell(ligne + 1, 1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=ligne + 1, start_column=1, end_row=ligne + 7, end_column=6)
    try:
        from openpyxl.chart import BarChart, Reference
        base = 5
        gr = BarChart(); gr.type, gr.style, gr.title = "bar", 10, "Répartition des tickets"
        gr.add_data(Reference(ws, min_col=2, min_row=base, max_row=base + 4), titles_from_data=False)
        gr.set_categories(Reference(ws, min_col=1, min_row=base, max_row=base + 4))
        gr.legend, gr.height, gr.width = None, 6.5, 12
        ws.add_chart(gr, "H5")
    except Exception:
        log.warning("Graphique Excel non ajouté")
    for k in range(5, 5 + len(chiffres)):
        ws.cell(k, 1).fill = PatternFill("solid", fgColor="F4F5F6")
        ws.cell(k, 2).font = Font(bold=True, size=12, color="FF4C29" if ws.cell(k, 1).value == "En retard" and ws.cell(k, 2).value else "082032")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 18
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16

    def feuille(nom, titres, lignes, largeurs):
        sh = wb.create_sheet(nom)
        sh.append(titres)
        for c in sh[1]:
            c.font, c.fill, c.alignment = blanc, entete, Alignment(vertical="center")
        for ligne_ in lignes:
            r = sh.max_row + 1
            for k, v in enumerate(ligne_, 1):
                c = _ecrire(sh, r, k, v)
                c.border, c.alignment = Border(bottom=thin), Alignment(wrap_text=True, vertical="top")
        for col, w in zip("ABCDEFG", largeurs):
            sh.column_dimensions[col].width = w
        sh.freeze_panes = "A2"
        return sh

    t = feuille("Tickets", HEAD, _rows(tickets, tracking, noms), (10, 42, 24, 14, 14, 38, 38))
    for k, i in enumerate(tickets, 2):
        if tracking[i]["situation"] == "en_retard":
            for c in t[k]:
                c.fill = retard
    t.auto_filter.ref = t.dimensions
    couleurs = {"En retard": "FFE1D8", "Fermé": "E6EAEE", "En attente": "FFF0D6"}
    for k, i in enumerate(tickets, 2):
        lib = STATUT.get(tickets[i]["statut"], "")
        if lib in couleurs and tracking[i]["situation"] != "en_retard":
            t.cell(k, 4).fill = PatternFill("solid", fgColor=couleurs[lib])
    t.page_setup.orientation, t.page_setup.fitToWidth, t.page_setup.fitToHeight = "landscape", 1, 0
    t.sheet_properties.pageSetUpPr.fitToPage = True
    ch = _charge(tickets, tracking, noms)
    if ch:
        feuille("Charge équipe", ["Membre", "Tickets en cours", "Dont en retard", "Avancement moyen (%)"],
                [[x["nom"], x["n"], x["late"], x["moy"]] for x in ch], (28, 18, 16, 22))
    if priorites or risques:
        lignes = [["Priorité", f"T-{p['id']:03d} · {p.get('titre', '')}", " · ".join(p.get("raisons", []))] for p in (priorites or [])[:8]]
        lignes += [["Risque " + ("élevé" if r.get("risque") == "eleve" else "modéré"), f"T-{r['id']:03d} · {r.get('titre', '')}", r.get("prediction", "")]
                   for r in (risques or [])[:10]]
        feuille("Priorités et risques", ["Type", "Ticket", "Détail"], lignes, (16, 46, 80))
    if evolutions:
        feuille("Évolution", ["Date", "Évolution"], [[_heure(e.get("t")), e.get("txt", "")] for e in evolutions[:30]], (14, 110))
    feuille("Recommandations", ["Recommandation", "Décision"],
            [[texte, {"suivie": "Suivie", "rejetee": "Rejetée"}.get(dec or "", "À examiner")] for texte, dec in recos], (110, 14))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
