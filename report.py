"""Génération du rapport de décision : texte, HTML (e-mail) et PDF (pièce jointe)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape

import numpy as np
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from ahp_core import CR_THRESHOLD, Analysis, Decision, percent, value_label

BLUE = colors.HexColor("#1f5fd0")
INK = colors.HexColor("#1b2a3d")
SOFT = colors.HexColor("#5a6a7e")
LINE = colors.HexColor("#d9e0e9")
TINT = colors.HexColor("#eef3fb")
WARN = colors.HexColor("#a4400f")
WARN_TINT = colors.HexColor("#fdf0e8")
PAGE_WIDTH = A4[0] - 3.6 * cm


@dataclass(frozen=True)
class ReportMeta:
    author: str
    generated_at: datetime


def headline(decision: Decision) -> str:
    winners = [decision.candidates[c] for c in decision.winners]
    if len(winners) == 1:
        return f"Candidat recommandé : {winners[0]} ({percent(float(decision.scores[decision.winners[0]]))})"
    return f"Égalité en tête entre {' et '.join([', '.join(winners[:-1]), winners[-1]])}"


def warnings_for(decision: Decision) -> list[str]:
    messages = []
    if decision.inconsistent_matrices:
        messages.append(
            "Jugements incohérents (CR supérieur à 10 %) : " + " ; ".join(decision.inconsistent_matrices) + "."
        )
    if decision.untouched_matrices:
        messages.append(
            "Comparaisons laissées à égalité partout : " + " ; ".join(decision.untouched_matrices) + "."
        )
    return messages


def subject(decision: Decision) -> str:
    return f"Rapport AHP : {decision.job}" if decision.job else "Rapport AHP de sélection de candidats"


def filename(meta: ReportMeta) -> str:
    return f"rapport_ahp_{meta.generated_at:%Y-%m-%d_%H%M}.pdf"


def _consistency_rows(decision: Decision) -> list[tuple[str, Analysis]]:
    rows = [("Pondération des critères", decision.criteria_analysis)]
    rows += [(f"Candidats selon « {c} »", a) for c, a in zip(decision.criteria, decision.candidate_analyses)]
    return rows


def _status(analysis: Analysis) -> str:
    return "Cohérent" if analysis.is_consistent else "À revoir"


def build_text(decision: Decision, meta: ReportMeta) -> str:
    lines = [
        "RAPPORT DE DÉCISION AHP",
        f"Poste : {decision.job or 'non précisé'}",
        f"Évaluation réalisée par {meta.author} le {meta.generated_at:%d/%m/%Y à %H:%M}",
        "",
        headline(decision),
        "",
    ]
    lines += [f"Attention : {message}" for message in warnings_for(decision)]
    lines += ["", "Classement"]
    lines += [
        f"{decision.ranks[c]}. {decision.candidates[c]} : {percent(float(decision.scores[c]))}"
        for c in decision.order
    ]
    lines += ["", "Poids des critères"]
    lines += [
        f"- {name} : {percent(float(weight))}"
        for name, weight in zip(decision.criteria, decision.criteria_analysis.weights)
    ]
    lines += ["", "Cohérence (seuil : CR inférieur ou égal à 10 %)"]
    lines += [f"- {name} : CR {percent(a.cr)} ({_status(a)})" for name, a in _consistency_rows(decision)]
    lines += ["", "Le détail complet des matrices figure dans le PDF joint."]
    return "\n".join(lines)


def _html_table(headers: list[str], rows: list[list[str]], first_left: int = 1) -> str:
    th = "padding:8px 10px;border-bottom:2px solid #1f5fd0;font-size:13px;color:#5a6a7e;"
    td = "padding:8px 10px;border-bottom:1px solid #d9e0e9;font-size:14px;color:#1b2a3d;"
    def align(index: int) -> str:
        return "left" if index < first_left else "right"
    head = "".join(f'<th style="{th}text-align:{align(i)}">{h}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td style="{td}text-align:{align(i)}">{cell}</td>' for i, cell in enumerate(row)) + "</tr>"
        for row in rows
    )
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        f'style="border-collapse:collapse;width:100%;margin:0 0 24px"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def build_html(decision: Decision, meta: ReportMeta) -> str:
    h2 = 'style="font-size:17px;color:#1b2a3d;margin:24px 0 10px"'
    warnings = "".join(
        f'<p style="margin:0 0 16px;padding:12px 14px;background:#fdf0e8;color:#7d3009;font-size:14px;'
        f'border-left:4px solid #c2541a"><strong>Attention.</strong> {escape(m)}</p>'
        for m in warnings_for(decision)
    )
    ranking = _html_table(
        ["Rang", "Candidat", "Score global"],
        [[str(decision.ranks[c]), escape(decision.candidates[c]), percent(float(decision.scores[c]))]
         for c in decision.order],
        first_left=2,
    )
    weights = _html_table(
        ["Critère", "Poids"],
        [[escape(n), percent(float(w))] for n, w in zip(decision.criteria, decision.criteria_analysis.weights)],
    )
    detail = _html_table(
        ["Candidat"] + [escape(c) for c in decision.criteria],
        [[escape(decision.candidates[c])] + [percent(float(v)) for v in decision.local[c]] for c in decision.order],
    )
    consistency = _html_table(
        ["Comparaisons", "CI", "CR", "Statut"],
        [[escape(n), f"{a.ci:.4f}".replace(".", ","), percent(a.cr), _status(a)]
         for n, a in _consistency_rows(decision)],
    )
    return f"""\
<!doctype html>
<html lang="fr"><body style="margin:0;background:#f4f7fb;padding:24px 12px">
<div style="max-width:680px;margin:0 auto;background:#ffffff;padding:28px;font-family:Arial,Helvetica,sans-serif">
<h1 style="font-size:22px;color:#1b2a3d;margin:0 0 4px">Rapport de décision AHP</h1>
<p style="margin:0;color:#5a6a7e;font-size:14px">Poste : {escape(decision.job or "non précisé")}<br>
Évaluation réalisée par {escape(meta.author)} le {meta.generated_at:%d/%m/%Y à %H:%M}</p>
<p style="margin:20px 0;padding:16px 18px;background:#1f5fd0;color:#ffffff;font-size:19px;font-weight:bold">
{escape(headline(decision))}</p>
{warnings}
<h2 {h2}>Classement final</h2>{ranking}
<h2 {h2}>Poids des critères</h2>{weights}
<h2 {h2}>Priorité de chaque candidat par critère</h2>
<div style="overflow-x:auto">{detail}</div>
<h2 {h2}>Contrôle de cohérence</h2>{consistency}
<p style="color:#5a6a7e;font-size:13px;margin:0">Un jugement est considéré comme cohérent lorsque son ratio
CR ne dépasse pas {percent(CR_THRESHOLD, 0)}. Le détail complet des matrices figure dans le PDF joint.</p>
</div></body></html>"""


# --- PDF ---------------------------------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    make = lambda name, **kw: ParagraphStyle(name, parent=base, textColor=INK, **kw)
    return {
        "title": make("t", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4),
        "meta": ParagraphStyle("m", parent=base, textColor=SOFT, fontSize=9.5, leading=13),
        "h2": make("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceBefore=14, spaceAfter=6),
        "h3": make("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=10, spaceAfter=4),
        "body": make("b", fontSize=9.5, leading=13),
        "cell": make("c", fontSize=8.5, leading=10.5),
        "hero": ParagraphStyle("h", parent=base, textColor=colors.white, fontName="Helvetica-Bold", fontSize=14, leading=18),
        "warn": ParagraphStyle("w", parent=base, textColor=WARN, fontSize=9.5, leading=13),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(xml_escape(text), style)


def _table_style(numeric_from: int = 1) -> list:
    return [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), SOFT),
        ("LINEBELOW", (0, 0), (-1, 0), 1, BLUE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (numeric_from, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]


def _bar(ratio: float, width: float, highlight: bool) -> Drawing:
    drawing = Drawing(width, 9)
    drawing.add(Rect(0, 0, max(1, width * ratio), 9, rx=2, ry=2, fillColor=BLUE if highlight else colors.HexColor("#c3cedb"), strokeColor=None))
    return drawing


def _ranking_table(decision: Decision, s: dict) -> Table:
    bar_width = PAGE_WIDTH - 8.6 * cm
    top = float(decision.scores.max())
    rows = [["Rang", "Candidat", "Score", ""]]
    for c in decision.order:
        rows.append([
            str(int(decision.ranks[c])), _p(decision.candidates[c], s["cell"]), percent(float(decision.scores[c])),
            _bar(float(decision.scores[c]) / top, bar_width - 16, decision.ranks[c] == 1),
        ])
    table = Table(rows, colWidths=[1.2 * cm, 5.6 * cm, 1.8 * cm, bar_width + 0.0], repeatRows=1)
    table.setStyle(TableStyle(_table_style(2) + [("ALIGN", (3, 0), (3, -1), "LEFT"), ("LEFTPADDING", (3, 0), (3, -1), 10)]))
    return table


def _pair_table(names: list[str], weights: np.ndarray, title: str, s: dict) -> Table:
    rows = [[title, "Poids"]] + [[_p(n, s["cell"]), percent(float(w))] for n, w in zip(names, weights)]
    table = Table(rows, colWidths=[PAGE_WIDTH - 2.4 * cm, 2.4 * cm], repeatRows=1)
    table.setStyle(TableStyle(_table_style(1)))
    return table


def _matrix_table(names: list[str], analysis: Analysis, s: dict) -> Table:
    n = analysis.n
    label_width = 4.6 * cm
    weight_width = 1.7 * cm
    cell_width = (PAGE_WIDTH - label_width - weight_width) / n
    font_size = 8.5 if n <= 8 else 7
    rows = [[""] + [str(k + 1) for k in range(n)] + ["Poids"]]
    for i in range(n):
        rows.append(
            [_p(f"{i + 1}. {names[i]}", s["cell"])]
            + [value_label(float(analysis.matrix[i, j])) for j in range(n)]
            + [percent(float(analysis.weights[i]))]
        )
    table = Table(rows, colWidths=[label_width] + [cell_width] * n + [weight_width], repeatRows=1)
    style = _table_style(1) + [("FONTSIZE", (1, 0), (-1, -1), font_size), ("ALIGN", (1, 0), (-2, -1), "CENTER")]
    for i in range(n):
        style.append(("TEXTCOLOR", (i + 1, i + 1), (i + 1, i + 1), SOFT))
        for j in range(i + 1, n):
            style.append(("BACKGROUND", (j + 1, i + 1), (j + 1, i + 1), TINT))
    table.setStyle(TableStyle(style))
    return table


def _analysis_block(title: str, names: list[str], analysis: Analysis, s: dict) -> KeepTogether:
    summary = (
        f"Lambda max = {analysis.lambda_max:.4f}   CI = {analysis.ci:.4f}   RI = {analysis.ri:.2f}   "
        f"CR = {percent(analysis.cr, 2)}   {_status(analysis)}"
    ).replace(".", ",")
    style = s["warn"] if not analysis.is_consistent else s["meta"]
    return KeepTogether([_p(title, s["h3"]), _matrix_table(names, analysis, s), Spacer(1, 3), _p(summary, style)])


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(SOFT)
    canvas.drawString(1.8 * cm, 1 * cm, "Rapport de décision AHP")
    canvas.drawRightString(A4[0] - 1.8 * cm, 1 * cm, f"Page {document.page}")
    canvas.restoreState()


def build_pdf(decision: Decision, meta: ReportMeta) -> bytes:
    s = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        title="Rapport de décision AHP", author=meta.author, subject=decision.job or "Sélection de candidats",
    )
    hero = Table([[_p(headline(decision), s["hero"])]], colWidths=[PAGE_WIDTH])
    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story = [
        _p("Rapport de décision AHP", s["title"]),
        _p(f"Poste : {decision.job or 'non précisé'}", s["meta"]),
        _p(f"Évaluation réalisée par {meta.author} le {meta.generated_at:%d/%m/%Y à %H:%M}", s["meta"]),
        Spacer(1, 10), hero, Spacer(1, 8),
    ]
    for message in warnings_for(decision):
        box = Table([[_p("Attention. " + message, s["warn"])]], colWidths=[PAGE_WIDTH])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_TINT), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
        story += [box, Spacer(1, 6)]

    story += [_p("Classement final", s["h2"]), _ranking_table(decision, s)]
    story += [_p("Poids des critères", s["h2"]),
              _pair_table(decision.criteria, decision.criteria_analysis.weights, "Critère", s)]

    story.append(_p("Priorité de chaque candidat par critère", s["h2"]))
    k = len(decision.criteria)
    label_width = 4.2 * cm
    width = (PAGE_WIDTH - label_width) / k
    rows = [[""] + [str(i + 1) for i in range(k)]]
    rows += [[_p(decision.candidates[c], s["cell"])] + [percent(float(v), 1 if k <= 8 else 0) for v in decision.local[c]]
             for c in decision.order]
    local = Table(rows, colWidths=[label_width] + [width] * k, repeatRows=1)
    local.setStyle(TableStyle(_table_style(1) + ([("FONTSIZE", (1, 1), (-1, -1), 7)] if k > 8 else [])))
    story += [
        local, Spacer(1, 4),
        _p("Critères : " + " ; ".join(f"{i + 1}. {name}" for i, name in enumerate(decision.criteria)), s["meta"]),
    ]

    story.append(_p("Détail des comparaisons par paires", s["h2"]))
    story.append(_p(
        "Les cases teintées correspondent aux saisies du recruteur ; les autres sont calculées "
        "automatiquement par réciprocité (a_ji = 1 / a_ij). Les poids sont issus du vecteur propre principal. "
        f"Un jugement est cohérent lorsque CR ne dépasse pas {percent(CR_THRESHOLD, 0)}.", s["body"],
    ))
    story.append(_analysis_block("Pondération des critères", decision.criteria, decision.criteria_analysis, s))
    for criterion, analysis in zip(decision.criteria, decision.candidate_analyses):
        story.append(_analysis_block(f"Candidats selon « {criterion} »", decision.candidates, analysis, s))

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
