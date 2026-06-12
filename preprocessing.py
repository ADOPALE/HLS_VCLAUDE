"""
preprocessing.py — Filtrage et préparation des flux actifs par jour.

Sélectionne les flux Volume avec quantité > 0 pour le jour simulé,
calcule volumes et poids, et identifie les tournées mutualisées.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

import config
from models import Flux, Contenant

logger = logging.getLogger(__name__)


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
    - Quantité pour le jour_idx > 0
    - Fonction support dans la liste fonctions_incluses

    Args:
        flux_brut: Liste brute des flux depuis data_loader.parse_m_flux().
        day_idx: Index du jour 0=Lundi … 6=Dimanche.
        fonctions_incluses: Fonctions support à simuler.
        contenants_data: Dict des contenants pour calcul poids/volume.
        circulation_factor: Facteur de circulation en % (non utilisé ici, transmis au moteur).

    Returns:
        Liste de Flux Pydantic triés par heure de disponibilité puis par urgence.
    """
    active = []
    for f in flux_brut:
        # Filtres primaires
        if f.get("nature", "").strip() != config.FLUX_VOLUME:
            continue
        qty = f.get("quantites", {}).get(day_idx, 0) or 0
        if qty <= config.MIN_QUANTITY:
            continue
        if fonctions_incluses and f.get("fonction_support", "") not in fonctions_incluses:
            continue
        if not f.get("site_depart") or not f.get("site_arrivee"):
            continue

        # Calcul poids / volume
        cont_name = f.get("type_contenant", "")
        cont_data = contenants_data.get(cont_name, {})
        surface_contenant = cont_data.get("longueur", 0) * cont_data.get("largeur", 0)
        poids_unit = (
            cont_data.get("poids_plein", 0)
            if f.get("statut_plein_vide", "").lower() == "plein"
            else cont_data.get("poids_vide", 0)
        )

        heure_dispo = f.get("heure_dispo")
        heure_max = f.get("heure_max_livraison")

        # Gestion des fenêtres horaires manquantes
        if heure_dispo is None:
            heure_dispo = config.DEFAULT_RH["start_min"]
        if heure_max is None:
            heure_max = config.DEFAULT_RH["end_max"]

        flux = Flux(
            id_flux=f["id_flux"],
            site_depart=f["site_depart"],
            site_arrivee=f["site_arrivee"],
            fonction_support=f.get("fonction_support", ""),
            nature_flux=f.get("nature_flux", ""),
            type_contenant=cont_name,
            quantite=int(qty),
            statut_plein_vide=f.get("statut_plein_vide", ""),
            statut_propre_sale=f.get("statut_propre_sale", ""),
            aller_retour=f.get("aller_retour", ""),
            transport_mixte=f.get("transport_mixte", False),
            regle_exclusion=f.get("regle_exclusion"),
            tournee_mutualisee=f.get("tournee_mutualisee", False),
            nom_tournee=f.get("nom_tournee"),
            heure_dispo=int(heure_dispo),
            heure_max_livraison=int(heure_max),
            urgent=f.get("urgent", False),
            volume_total=surface_contenant * int(qty),
            poids_total=poids_unit * int(qty),
        )
        active.append(flux)

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
        f.get("fonction_support", "")
        for f in flux_brut
        if f.get("nature", "").strip() == config.FLUX_VOLUME
        and f.get("fonction_support", "").strip()
    ))
