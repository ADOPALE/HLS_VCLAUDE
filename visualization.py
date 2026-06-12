"""
visualization.py — Visualisations Plotly pour l'interface OptiFLUX.

Fournit le diagramme de Gantt par poste chauffeur, la timeline détaillée
et la vue planning des quais.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
import plotly.express as px

import config
from models import PosteChaufeur, Tournee
from time_windows import minutes_to_hhmm


def make_gantt_postes(
    postes: List[PosteChaufeur],
    titre: str = "Planning des postes chauffeurs",
) -> go.Figure:
    """
    Crée un diagramme de Gantt des postes chauffeurs.

    Axe X : temps (06:00 → 21:00)
    Axe Y : postes (un par véhicule/numéro de poste)
    Couleurs : par type d'opération

    Args:
        postes: Liste des postes chauffeurs.
        titre: Titre du graphique.

    Returns:
        Figure Plotly.
    """
    if not postes:
        fig = go.Figure()
        fig.update_layout(title=titre, annotations=[{
            "text": "Aucun poste à afficher",
            "xref": "paper", "yref": "paper",
            "x": 0.5, "y": 0.5, "showarrow": False
        }])
        return fig

    fig = go.Figure()
    op_colors = config.GANTT_COLORS

    for i, poste in enumerate(postes):
        label = f"Poste {poste.id_poste} — {poste.type_vehicule}"
        for step in poste.steps:
            dur = step.heure_fin - step.heure_debut
            if dur <= 0:
                continue
            color = op_colors.get(step.type_operation, "#CCCCCC")
            tooltip = (
                f"<b>{step.type_operation}</b><br>"
                f"Site: {step.site}<br>"
                f"Début: {minutes_to_hhmm(step.heure_debut)}<br>"
                f"Fin: {minutes_to_hhmm(step.heure_fin)}<br>"
                f"Durée: {dur} min"
            )
            if step.flux_ids:
                tooltip += f"<br>Flux: {step.flux_ids}"
            if step.nb_contenants:
                tooltip += f"<br>Contenants: {step.nb_contenants} × {step.type_contenant}"

            fig.add_trace(go.Bar(
                x=[dur],
                y=[label],
                base=[step.heure_debut],
                orientation="h",
                marker_color=color,
                hovertemplate=tooltip + "<extra></extra>",
                showlegend=False,
                name=step.type_operation,
            ))

    # Légende manuelle
    seen_ops = set()
    for poste in postes:
        for step in poste.steps:
            if step.type_operation not in seen_ops:
                seen_ops.add(step.type_operation)
                color = op_colors.get(step.type_operation, "#CCCCCC")
                fig.add_trace(go.Bar(
                    x=[0], y=[""],
                    marker_color=color,
                    name=step.type_operation,
                    showlegend=True,
                ))

    # Axe X en HH:MM
    tick_vals = list(range(360, 1261, 60))  # 06:00 à 21:00 par heure
    tick_text = [minutes_to_hhmm(v) for v in tick_vals]

    fig.update_layout(
        title=titre,
        barmode="overlay",
        xaxis=dict(
            title="Heure",
            tickvals=tick_vals,
            ticktext=tick_text,
            range=[360, 1260],
        ),
        yaxis=dict(title="Poste"),
        legend=dict(title="Type d'opération", orientation="h", yanchor="bottom", y=1.02),
        height=max(300, len(postes) * 60 + 150),
        font=dict(size=11),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


def make_timeline_poste(poste: PosteChaufeur) -> go.Figure:
    """
    Crée une timeline détaillée pour un poste chauffeur.

    Args:
        poste: Poste chauffeur.

    Returns:
        Figure Plotly (table interactive).
    """
    rows = []
    for step in poste.steps:
        rows.append({
            "Heure début": minutes_to_hhmm(step.heure_debut),
            "Heure fin": minutes_to_hhmm(step.heure_fin),
            "Durée (min)": step.heure_fin - step.heure_debut,
            "Opération": step.type_operation,
            "Site": step.site,
            "Flux": ", ".join(str(i) for i in step.flux_ids) if step.flux_ids else "",
            "Contenants": f"{step.nb_contenants}×{step.type_contenant}" if step.nb_contenants else "",
            "Taux rempl. (%)": f"{step.taux_remplissage_surface*100:.0f}" if step.taux_remplissage_surface else "",
            "Statut sanitaire": step.statut_sanitaire,
            "Dist. (km)": f"{step.distance_km:.1f}" if step.distance_km else "",
        })

    if not rows:
        fig = go.Figure()
        return fig

    keys = list(rows[0].keys())
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[f"<b>{k}</b>" for k in keys],
            fill_color="#1565C0",
            font=dict(color="white", size=12),
            align="left",
        ),
        cells=dict(
            values=[[r[k] for r in rows] for k in keys],
            fill_color=[["#f5f9ff" if i % 2 == 0 else "white" for i in range(len(rows))]],
            align="left",
            font=dict(size=11),
        )
    )])
    fig.update_layout(
        title=f"Poste {poste.id_poste} — {poste.type_vehicule} — Détail chronologique",
        margin=dict(t=50, b=10, l=10, r=10),
        height=max(300, len(rows) * 28 + 100),
    )
    return fig


def make_synthese_chart(resultats_jours: List[Dict[str, Any]]) -> go.Figure:
    """
    Crée un graphique de synthèse multi-jours (véhicules, km, postes).

    Args:
        resultats_jours: Liste de dicts résultats par jour.

    Returns:
        Figure Plotly.
    """
    if not resultats_jours:
        return go.Figure()

    jours = [r.get("jour", f"J{i}") for i, r in enumerate(resultats_jours)]
    nb_veh = [r.get("nb_vehicules", 0) for r in resultats_jours]
    nb_postes = [r.get("nb_postes", 0) for r in resultats_jours]
    km = [r.get("km_total", 0) for r in resultats_jours]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Véhicules", x=jours, y=nb_veh, marker_color="#1565C0"))
    fig.add_trace(go.Bar(name="Postes chauffeurs", x=jours, y=nb_postes, marker_color="#FFA726"))
    fig.add_trace(go.Scatter(
        name="Km totaux", x=jours, y=km, mode="lines+markers",
        yaxis="y2", marker_color="#4CAF50", line_width=2,
    ))

    fig.update_layout(
        title="Synthèse par jour simulé",
        barmode="group",
        xaxis=dict(title="Jour"),
        yaxis=dict(title="Nombre"),
        yaxis2=dict(title="Kilomètres", overlaying="y", side="right"),
        legend=dict(orientation="h"),
        height=400,
    )
    return fig
