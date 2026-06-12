"""
compatibility.py — Règles de compatibilité véhicule/site/contenant/mixité.

Centralise toutes les vérifications de compatibilité métier.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any

from models import Vehicule, Site, Flux
import config


def vehicule_compatible_flux(
    vehicule: Vehicule,
    flux: Flux,
    sites: Dict[str, Site],
) -> bool:
    """
    Vérifie si un véhicule peut transporter un flux donné.

    Conditions :
    1. Contenant compatible avec le véhicule
    2. Véhicule compatible avec le site de départ
    3. Véhicule compatible avec le site d'arrivée
    4. Si site sans quai : véhicule doit pouvoir opérer sans quai

    Args:
        vehicule: Modèle Vehicule.
        flux: Modèle Flux.
        sites: Dict des sites.

    Returns:
        True si toutes les conditions sont satisfaites.
    """
    # 1. Compatibilité contenant
    if not vehicule.compat_contenants.get(flux.type_contenant, False):
        return False

    # 2 & 3. Compatibilité sites
    for site_name in (flux.site_depart, flux.site_arrivee):
        site = sites.get(site_name)
        if site is None:
            return False
        if not site.compat_vehicules.get(vehicule.type_vehicule, False):
            return False
        # 4. Site sans quai
        if not site.presence_quai and not vehicule.peut_operer_sans_quai:
            return False

    return True


def peut_grouper_flux(
    flux1: Flux,
    flux2: Flux,
    etat_sanitaire_veh: str = config.SANITAIRE_PROPRE,
) -> bool:
    """
    Vérifie si deux flux peuvent être transportés simultanément dans le même véhicule.

    Règles :
    - Si l'un des flux a transport_mixte=False, ils ne peuvent pas cohabiter
      sauf s'ils ont le même statut propre/sale.
    - Si un flux a une règle d'exclusion, le statut de l'autre flux ne doit pas
      correspondre à la valeur exclue.

    Args:
        flux1: Premier flux.
        flux2: Deuxième flux.
        etat_sanitaire_veh: État sanitaire courant du véhicule.

    Returns:
        True si le groupage est autorisé.
    """
    s1 = flux1.statut_propre_sale
    s2 = flux2.statut_propre_sale

    # Même statut sanitaire → toujours groupable (pas de mixité)
    if s1 == s2:
        return True

    # Statuts différents : les deux doivent autoriser le transport mixte
    if not flux1.transport_mixte or not flux2.transport_mixte:
        return False

    # Vérification des règles d'exclusion
    if flux1.regle_exclusion and s2 == flux1.regle_exclusion:
        return False
    if flux2.regle_exclusion and s1 == flux2.regle_exclusion:
        return False

    return True


def get_vehicules_compatibles_flux(
    flux: Flux,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
) -> List[str]:
    """
    Retourne la liste des types de véhicules compatibles avec un flux donné.

    Args:
        flux: Flux à transporter.
        vehicules: Dict des véhicules disponibles.
        sites: Dict des sites.

    Returns:
        Liste triée des types de véhicules compatibles.
    """
    compatibles = [
        vtype
        for vtype, veh in vehicules.items()
        if veh.actif and vehicule_compatible_flux(veh, flux, sites)
    ]
    return compatibles


def etat_sanitaire_apres_chargement(
    etat_courant: str,
    flux: Flux,
) -> str:
    """
    Retourne l'état sanitaire du véhicule après chargement d'un flux.

    Un véhicule devient SALE s'il charge du SALE.
    Il reste PROPRE s'il charge du PROPRE.

    Args:
        etat_courant: État sanitaire courant ('Propre' ou 'Sale').
        flux: Flux chargé.

    Returns:
        Nouvel état sanitaire.
    """
    if flux.statut_propre_sale == config.SANITAIRE_SALE:
        return config.SANITAIRE_SALE
    return etat_courant


def vehicule_peut_charger(
    vehicule: Vehicule,
    flux: Flux,
    etat_sanitaire_veh: str,
    flux_deja_charges: List[Flux],
) -> bool:
    """
    Vérifie si un véhicule peut charger un flux supplémentaire en tenant compte
    de son état sanitaire courant et des flux déjà chargés.

    Args:
        vehicule: Modèle Vehicule.
        flux: Flux à charger.
        etat_sanitaire_veh: État sanitaire courant du véhicule.
        flux_deja_charges: Liste des flux déjà chargés.

    Returns:
        True si le chargement est autorisé.
    """
    # Véhicule sale ne peut pas charger du propre
    if etat_sanitaire_veh == config.SANITAIRE_SALE and flux.statut_propre_sale == config.SANITAIRE_PROPRE:
        return False

    # Vérification mixité avec les flux déjà chargés
    for fc in flux_deja_charges:
        if not peut_grouper_flux(fc, flux, etat_sanitaire_veh):
            return False

    return True
