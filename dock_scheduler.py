"""
dock_scheduler.py — Planning des quais OptiFLUX.

Vérifie et résout les conflits de capacité de quai sur chaque site.
Chaque arrivée de véhicule sur un site génère une occupation de quai
pendant la durée (mise à quai + manutention).
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from models import Tournee, PosteChaufeur, Site, Vehicule, StepOperation

logger = logging.getLogger(__name__)


def build_dock_planning(
    postes: List[PosteChaufeur],
    sites: Dict[str, Site],
    vehicules: Dict[str, Vehicule],
) -> List[Dict[str, Any]]:
    """
    Construit le planning des quais à partir des postes chauffeurs.

    Pour chaque mise à quai, enregistre : site, heure d'arrivée,
    heure début mise à quai, heure fin, véhicule, poste, flux.

    Args:
        postes: Liste des postes chauffeurs.
        sites: Dict des sites.
        vehicules: Dict des véhicules.

    Returns:
        Liste de dicts décrivant chaque occupation de quai.
    """
    planning = []
    for poste in postes:
        for step in poste.steps:
            if step.type_operation != config.OP_MISE_A_QUAI:
                continue
            site = sites.get(step.site)
            if site is None:
                continue
            planning.append({
                "site": step.site,
                "capacite_quai": site.capacite_quai,
                "heure_arrivee": step.heure_debut,
                "heure_debut_quai": step.heure_debut,
                "heure_fin_quai": step.heure_fin,
                "heure_depart": step.heure_fin,
                "vehicule": poste.type_vehicule,
                "poste_id": poste.id_poste,
                "operation": step.type_operation,
                "flux_ids": step.flux_ids,
            })
    return planning


def detecter_conflits_quai(
    dock_planning: List[Dict[str, Any]],
    sites: Dict[str, Site],
) -> List[Dict[str, Any]]:
    """
    Détecte les conflits de capacité de quai.

    Un conflit existe quand plus de `capacite_quai` véhicules sont
    simultanément en quai sur un même site.

    Args:
        dock_planning: Planning des quais généré par build_dock_planning().
        sites: Dict des sites.

    Returns:
        Liste de dicts décrivant les conflits :
        {site, heure_conflit, nb_vehicules, capacite, vehicules_concernes}
    """
    from collections import defaultdict

    conflits = []
    # Grouper par site
    par_site: Dict[str, List[Dict]] = defaultdict(list)
    for entry in dock_planning:
        par_site[entry["site"]].append(entry)

    for site_name, entries in par_site.items():
        cap = sites.get(site_name, None)
        if cap is None:
            continue
        capacite = cap.capacite_quai

        # Générer les événements (arrivée/départ)
        events = []
        for e in entries:
            events.append((e["heure_debut_quai"], +1, e))
            events.append((e["heure_fin_quai"], -1, e))
        events.sort(key=lambda x: (x[0], x[1]))

        current_count = 0
        current_veh = []
        for heure, delta, entry in events:
            if delta == +1:
                current_count += 1
                current_veh.append(entry)
            else:
                current_count -= 1
                current_veh = [v for v in current_veh if v != entry]

            if current_count > capacite:
                conflits.append({
                    "site": site_name,
                    "heure_conflit": heure,
                    "nb_vehicules": current_count,
                    "capacite": capacite,
                    "vehicules": [v["vehicule"] for v in current_veh],
                })

    return conflits


def resoudre_conflits_quai(
    postes: List[PosteChaufeur],
    dock_planning: List[Dict[str, Any]],
    conflits: List[Dict[str, Any]],
    sites: Dict[str, Site],
) -> Tuple[List[PosteChaufeur], List[Dict[str, Any]]]:
    """
    Tente de résoudre les conflits de quai par décalage des arrivées.

    Note : une résolution complète nécessite une réoptimisation des tournées,
    ce qui dépasse le scope de cette fonction. Les conflits sont signalés
    dans les contrôles de conformité.

    Args:
        postes: Liste des postes chauffeurs.
        dock_planning: Planning des quais.
        conflits: Conflits détectés.
        sites: Dict des sites.

    Returns:
        Tuple (postes_ajustes, conflits_residuels).
    """
    # Dans cette version, on retourne les conflits comme non résolus
    # pour signalement dans l'interface
    conflits_residuels = conflits.copy()
    return postes, conflits_residuels
