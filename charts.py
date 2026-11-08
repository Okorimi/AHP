"""Graphiques interactifs Plotly de la page de résultats."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from ahp_core import Decision

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
HIGHLIGHT = "#1f5fd0"
MUTED = "#c3cedb"
OTHER = "#8a94a3"
INK = "#1b2a3d"
INK_SOFT = "#5a6a7e"
GRID = "#e6ebf1"
SURFACE = "#ffffff"
FONT = "Public Sans, Source Sans Pro, sans-serif"
SEQUENTIAL = [[0.0, "#eaf2fc"], [0.7, "#8fbcf0"], [1.0, "#174f9c"]]
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


def _layout(height: int, **kwargs) -> dict:
    layout = dict(
        height=height,
        margin=dict(l=8, r=40, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=14, color=INK),
        hoverlabel=dict(bgcolor=SURFACE, font=dict(color=INK, family=FONT), bordercolor=GRID),
        showlegend=False,
    )
    layout.update(kwargs)
    return layout


def _value_axis(maximum: float) -> dict:
    return dict(
        range=[0, maximum], ticksuffix=" %", gridcolor=GRID, zeroline=False, tickfont=dict(color=INK_SOFT),
        fixedrange=True,
    )


def _category_axis() -> dict:
    return dict(automargin=True, autorange="reversed", showgrid=False, ticks="", ticksuffix="  ", fixedrange=True)


def _height(rows: int, extra: int = 56) -> int:
    return max(160, extra + 46 * rows)


def ranking_chart(decision: Decision) -> go.Figure:
    order = decision.order
    names = [decision.candidates[c] for c in order]
    values = [float(decision.scores[c] * 100) for c in order]
    winners = set(decision.winners)
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h", width=0.56,
        marker=dict(color=[HIGHLIGHT if c in winners else MUTED for c in order], cornerradius=4),
        text=[f"{v:.1f} %".replace(".", ",") for v in values],
        textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Score global : %{x:.1f} %<extra></extra>",
    ))
    fig.update_layout(**_layout(_height(len(names))), xaxis=_value_axis(max(values) * 1.18),
                      yaxis=_category_axis())
    return fig


def weights_chart(decision: Decision) -> go.Figure:
    weights = decision.criteria_analysis.weights * 100
    order = np.argsort(-weights, kind="stable")
    names = [decision.criteria[i] for i in order]
    values = [float(weights[i]) for i in order]
    fig = go.Figure(go.Bar(
        x=values, y=names, orientation="h", width=0.56,
        marker=dict(color=SERIES[0], cornerradius=4),
        text=[f"{v:.1f} %".replace(".", ",") for v in values],
        textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Poids : %{x:.1f} %<extra></extra>",
    ))
    fig.update_layout(**_layout(_height(len(names))), xaxis=_value_axis(max(values) * 1.18),
                      yaxis=_category_axis())
    return fig


def _folded_contributions(decision: Decision) -> tuple[list[str], np.ndarray, list[str]]:
    """Limite le graphique à 8 couleurs : au-delà, les plus petits critères sont regroupés."""
    criteria = decision.criteria
    contributions = decision.contributions * 100
    if len(criteria) <= len(SERIES):
        return criteria, contributions, SERIES[: len(criteria)]
    weights = decision.criteria_analysis.weights
    kept = sorted(np.argsort(-weights, kind="stable")[: len(SERIES) - 1])
    rest = [i for i in range(len(criteria)) if i not in set(kept)]
    names = [criteria[i] for i in kept] + ["Autres critères"]
    values = np.column_stack([contributions[:, kept], contributions[:, rest].sum(axis=1)])
    return names, values, SERIES[: len(SERIES) - 1] + [OTHER]


def contribution_chart(decision: Decision) -> go.Figure:
    order = decision.order
    candidates = [decision.candidates[c] for c in order]
    criteria, values, colors = _folded_contributions(decision)
    fig = go.Figure()
    for k, criterion in enumerate(criteria):
        fig.add_bar(
            name=criterion, x=[float(values[c, k]) for c in order], y=candidates, orientation="h", width=0.56,
            marker=dict(color=colors[k], line=dict(color=SURFACE, width=2)),
            hovertemplate=f"<b>%{{y}}</b><br>{_plain(criterion)} : %{{x:.1f}} points<extra></extra>",
        )
    fig.update_layout(
        **_layout(_height(len(candidates), 96), showlegend=True, barmode="stack",
                  margin=dict(l=8, r=16, t=48, b=8),
                  legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text="", traceorder="normal", itemclick=False,
                              itemdoubleclick=False)),
        xaxis=dict(range=[0, float(max(decision.scores) * 100 * 1.04)], ticksuffix=" pts", gridcolor=GRID,
                   zeroline=False, tickfont=dict(color=INK_SOFT), fixedrange=True),
        yaxis=_category_axis(),
    )
    return fig


def _plain(text: str) -> str:
    """Neutralise les caractères interprétés par les gabarits et le HTML de Plotly."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace("%", "%%").replace("{", "(").replace("}", ")")


def heatmap_chart(decision: Decision) -> go.Figure:
    order = decision.order
    z = decision.local[order] * 100
    fig = go.Figure(go.Heatmap(
        z=z, x=decision.criteria, y=[decision.candidates[c] for c in order],
        colorscale=SEQUENTIAL, zmin=0, zmax=100, xgap=2, ygap=2,
        text=[[f"{v:.0f} %" for v in row] for row in z], texttemplate="%{text}",
        textfont=dict(size=14),
        colorbar=dict(title=dict(text="Priorité", side="top"), ticksuffix=" %", thickness=10, len=0.9, outlinewidth=0),
        hovertemplate="<b>%{y}</b><br>%{x} : %{z:.1f} %<extra></extra>",
    ))
    fig.update_layout(
        **_layout(max(190, 72 + 56 * len(order)), margin=dict(l=8, r=8, t=8, b=8)),
        xaxis=dict(side="top", showgrid=False, ticks="", automargin=True, fixedrange=True),
        yaxis=dict(autorange="reversed", showgrid=False, ticks="", ticksuffix="  ", automargin=True, fixedrange=True),
    )
    return fig
