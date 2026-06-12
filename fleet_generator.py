"""
fleet_generator.py — Construction des objets métier depuis les DataFrames importés.
Transforme les DataFrames de data_loader en dictionnaires de modèles Pydantic.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from config import DOCK_CAPACITY_DEFAULT, DOCK_CAPACITY_OVERRIDES
from models import Site, Vehicule, Contenant

logger = logging.getLogger(__name__)


def build_sites(
    df_sites: pd.DataFrame,
    capacites_override: Optional[Dict[str, int]] = None,
) -> Dict[str, Site]:
    """
    Construit le dictionnaire des sites depuis le DataFrame param Sites.

    Args:
        df_sites: DataFrame de l'onglet param Sites.
        capacites_override: Capacités de quai personnalisées {libelle: capacite}.

    Returns:
        Dictionnaire {libelle: Site}.

    Example:
        >>> sites = build_sites(df_sites)
        >>> sites["HLS"].capacite_quai
        6
    """
    sites: Dict[str, Site] = {}

    # Colonnes de compatibilité véhicule = toutes sauf les colonnes de base
    base_cols = {"Libellé", "Adresses", "Présence de quai"}

    for _, row in df_sites.iterrows():
        libelle = str(row.get("Libellé", "")).strip()
        if not libelle:
            continue

        adresse = str(row.get("Adresses", "")).strip()
        presence_quai = bool(row.get("Présence de quai", False))

        # Capacité quai : override utilisateur > override hard > défaut
        if capacites_override and libelle in capacites_override:
            capacite_quai = int(capacites_override[libelle])
        elif libelle in DOCK_CAPACITY_OVERRIDES:
            capacite_quai = DOCK_CAPACITY_OVERRIDES[libelle]
        else:
            capacite_quai = DOCK_CAPACITY_DEFAULT

        # Compatibilités véhicule
        compat = {}
        for col in df_sites.columns:
            if col.strip() not in base_cols and col.strip():
                val = row.get(col)
                if val is not None:
                    compat[str(col).strip()] = bool(val)

        sites[libelle] = Site(
            libelle=libelle,
            adresse=adresse,
            presence_quai=presence_quai,
            capacite_quai=capacite_quai,
            compatibilite_vehicules=compat,
        )

    logger.info(f"{len(sites)} sites chargés.")
    return sites


def build_vehicules(df_vehicules: pd.DataFrame) -> Dict[str, Vehicule]:
    """
    Construit le dictionnaire des véhicules depuis le DataFrame param Véhicules.

    Args:
        df_vehicules: DataFrame de l'onglet param Véhicules.

    Returns:
        Dictionnaire {type: Vehicule}.
    """
    vehicules: Dict[str, Vehicule] = {}

    # Colonnes méta (non-compatibilité)
    meta_cols = {
        "Types", "Stationnement initial",
        "dim longueur interne (m)", "dim largeur interne (m)", "dim hauteur interne (m)",
        "Poids max chargement", "Consommation (L/km)", "Cout carburant (€/km)",
        "Cout carbone (kg/km)", "Présence hayon",
        "Temps de mise à quai - manœuvre, contact/admin (minutes)",
        "Manutention sans quai (minutes / contenants)",
        "Manutention avec quai (minutes / contenants)",
    }

    for _, row in df_vehicules.iterrows():
        type_ = str(row.get("Types", "")).strip()
        if not type_:
            continue

        # Compatibilités contenants
        compat = {}
        for col in df_vehicules.columns:
            col_stripped = col.strip()
            if col_stripped not in meta_cols and col_stripped:
                val = row.get(col)
                if val is not None:
                    compat[col_stripped] = bool(val)

        def _safe_float(col_name: str, default: float = 0.0) -> float:
            v = row.get(col_name)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        vehicules[type_] = Vehicule(
            type_=type_,
            stationnement_initial=str(row.get("Stationnement initial", "")).strip(),
            longueur_m=_safe_float("dim longueur interne (m)"),
            largeur_m=_safe_float("dim largeur interne (m)"),
            hauteur_m=_safe_float("dim hauteur interne (m)"),
            poids_max_t=_safe_float("Poids max chargement"),
            consommation_l_km=_safe_float("Consommation (L/km)"),
            cout_carburant_eur_km=_safe_float("Cout carburant (€/km)"),
            cout_carbone_kg_km=_safe_float("Cout carbone (kg/km)"),
            presence_hayon=bool(row.get("Présence hayon", False)),
            compatibilite_contenants=compat,
            temps_mise_a_quai_min=_safe_float(
                "Temps de mise à quai - manœuvre, contact/admin (minutes)", 10.0
            ),
            manutention_sans_quai_min_par_cont=row.get(
                "Manutention sans quai (minutes / contenants)"
            ),
            manutention_avec_quai_min_par_cont=_safe_float(
                "Manutention avec quai (minutes / contenants)", 0.25
            ),
        )

    logger.info(f"{len(vehicules)} types de véhicules chargés.")
    return vehicules


def build_contenants(df_contenants: pd.DataFrame) -> Dict[str, Contenant]:
    """
    Construit le dictionnaire des contenants depuis le DataFrame param Contenants.

    Args:
        df_contenants: DataFrame de l'onglet param Contenants.

    Returns:
        Dictionnaire {libelle: Contenant}.
    """
    contenants: Dict[str, Contenant] = {}

    for _, row in df_contenants.iterrows():
        libelle = str(row.get("libellé", "")).strip()
        if not libelle:
            continue

        def _sf(col: str, default: float = 0.0) -> float:
            v = row.get(col)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        contenants[libelle] = Contenant(
            libelle=libelle,
            longueur_m=_sf("dim longueur (m)"),
            largeur_m=_sf("dim largeur (m)"),
            poids_vide_t=_sf("Poids vide (T)"),
            poids_plein_t=_sf("Poids plein (T)"),
        )

    logger.info(f"{len(contenants)} contenants chargés.")
    return contenants


def get_fonctions_support(df_flux: pd.DataFrame) -> List[str]:
    """
    Extrait la liste des fonctions support uniques depuis M flux.

    Args:
        df_flux: DataFrame de l'onglet M flux.

    Returns:
        Liste triée des fonctions support.
    """
    col = "Fonction Support associée"
    if col not in df_flux.columns:
        return []
    return sorted(df_flux[col].dropna().unique().tolist())


def get_vehicule_stationnements(vehicules: Dict[str, Vehicule]) -> Dict[str, str]:
    """
    Retourne un dictionnaire {type_vehicule: stationnement_initial}.

    Args:
        vehicules: Dictionnaire des véhicules.

    Returns:
        Dictionnaire des stationnements initiaux.
    """
    return {veh_type: veh.stationnement_initial for veh_type, veh in vehicules.items()}
