"""
preprocessing.py — Filtrage et préparation des flux actifs par jour.

Sélectionne les flux Volume avec quantité > 0 pour le jour simulé,
calcule volumes et poids, et identifie les tournées mutualisées.
"""

from __future__ import annotations
import logging
import math
from typing import Any, Dict, List, Optional

import config
from models import Flux, Contenant

logger = logging.getLogger(__name__)


def _safe_int(value: Any, default: int = 0) -> int:
    """
    Convertit une valeur en int de façon défensive.

    Retourne `default` si la valeur est None, NaN, non numérique ou non convertissable.
    Évite les ValueError/TypeError courants avec les données Excel (NaN, None, strings vides).
    """
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return int(f)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convertit une valeur en float de façon défensive (NaN → default)."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    """Convertit une valeur en str, retourne default si None ou NaN."""
    if value is None:
        return default
    try:
        if isinstance(value, float) and math.isnan(value):
            return default
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def get_active_flux(
    flux_brut: List[Dict[str, Any]],
    day_idx: int,
    fonctions_incluses: List[str],
    contenants_data: Dict[str, Any],
    circulation_factor: float = 0.0,
) -> List[Flux]:
    """
    Filtre et retourne les flux actifs pour un jour donné.

    Critères d'inclusion :
    - Nature = 'Volume' (les 'Fréquences' sont ignorés)
    - Quantité pour le day_idx > 0
    - Fonction support dans fonctions_incluses

    Args:
        flux_brut: Liste brute des flux depuis data_loader.parse_m_flux().
        day_idx: Index du jour 0=Lundi … 6=Dimanche.
        fonctions_incluses: Fonctions support à simuler.
        contenants_data: Dict des contenants pour calcul poids/volume.
        circulation_factor: Facteur de circulation (non utilisé ici, transmis au moteur).

    Returns:
        Liste de Flux Pydantic triés par urgence puis heure de disponibilité.
    """
    active = []
    for f in flux_brut:
        # --- Filtres primaires ---
        if _safe_str(f.get("nature")) != config.FLUX_VOLUME:
            continue

        qty_raw = f.get("quantites", {}).get(day_idx, 0)
        qty = _safe_int(qty_raw, 0)
        if qty <= config.MIN_QUANTITY:
            continue

        fn_support = _safe_str(f.get("fonction_support"))
        if fonctions_incluses and fn_support not in fonctions_incluses:
            continue

        site_dep = _safe_str(f.get("site_depart"))
        site_arr = _safe_str(f.get("site_arrivee"))
        if not site_dep or not site_arr:
            continue

        # --- Calcul poids / volume ---
        cont_name = _safe_str(f.get("type_contenant"))
        cont_data = contenants_data.get(cont_name, {})
        lon = _safe_float(cont_data.get("longueur"))
        larg = _safe_float(cont_data.get("largeur"))
        surface_contenant = lon * larg

        statut_pv = _safe_str(f.get("statut_plein_vide"))
        poids_unit = (
            _safe_float(cont_data.get("poids_plein"))
            if statut_pv.lower() == "plein"
            else _safe_float(cont_data.get("poids_vide"))
        )

        # --- Fenêtres horaires ---
        heure_dispo = _safe_int(f.get("heure_dispo"), config.DEFAULT_RH["start_min"])
        heure_max = _safe_int(f.get("heure_max_livraison"), config.DEFAULT_RH["end_max"])

        # Sécurité : heure_max doit être > heure_dispo
        if heure_max <= heure_dispo:
            logger.warning(
                "Flux %s : heure_max (%d) ≤ heure_dispo (%d) — heure_max corrigée à end_max.",
                f.get("id_flux"), heure_max, heure_dispo,
            )
            heure_max = config.DEFAULT_RH["end_max"]

        # --- Construction du modèle Flux ---
        try:
            flux = Flux(
                id_flux=_safe_int(f.get("id_flux"), 0),
                site_depart=site_dep,
                site_arrivee=site_arr,
                fonction_support=fn_support,
                nature_flux=_safe_str(f.get("nature_flux")),
                type_contenant=cont_name,
                quantite=qty,
                statut_plein_vide=statut_pv,
                statut_propre_sale=_safe_str(f.get("statut_propre_sale")),
                aller_retour=_safe_str(f.get("aller_retour")),
                transport_mixte=bool(f.get("transport_mixte", False)),
                regle_exclusion=f.get("regle_exclusion") or None,
                tournee_mutualisee=bool(f.get("tournee_mutualisee", False)),
                nom_tournee=f.get("nom_tournee") or None,
                heure_dispo=heure_dispo,
                heure_max_livraison=heure_max,
                urgent=bool(f.get("urgent", False)),
                volume_total=surface_contenant * qty,
                poids_total=poids_unit * qty,
            )
            active.append(flux)
        except Exception as exc:
            logger.warning(
                "Flux id=%s ignoré — erreur de validation Pydantic : %s",
                f.get("id_flux", "?"), exc,
            )

    # Tri : urgents d'abord, puis par heure de dispo
    active.sort(key=lambda x: (not x.urgent, x.heure_dispo))
    return active


def get_tournees_mutualisees(flux_actifs: List[Flux]) -> Dict[str, List[int]]:
    """
    Groupe les flux actifs par tournée mutualisée.

    Args:
        flux_actifs: Liste des flux actifs du jour.

    Returns:
        Dict {nom_tournee: [id_flux, ...]} pour les flux avec tournée_mutualisée=True.
    """
    groupes: Dict[str, List[int]] = {}
    for f in flux_actifs:
        if f.tournee_mutualisee and f.nom_tournee:
            nom = str(f.nom_tournee).strip()
            groupes.setdefault(nom, []).append(f.id_flux)
    return groupes


def get_fonctions_support(flux_brut: List[Dict[str, Any]]) -> List[str]:
    """
    Retourne la liste des fonctions support distinctes présentes dans les flux Volume.

    Args:
        flux_brut: Liste brute des flux.

    Returns:
        Liste triée des fonctions support.
    """
    return sorted(set(
        _safe_str(f.get("fonction_support"))
        for f in flux_brut
        if _safe_str(f.get("nature")) == config.FLUX_VOLUME
        and _safe_str(f.get("fonction_support"))
    ))
