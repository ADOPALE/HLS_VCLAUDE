"""
route_builder.py — Reconstruction des tournées avec états dynamiques.

Produit la séquence chronologique détaillée d'une tournée :
trajets, chargements/déchargements, mises à quai, désinfections.
"""

from __future__ import annotations
import math
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from models import Flux, Vehicule, Site, Contenant, StepOperation

logger = logging.getLogger(__name__)


def build_route_steps(
    flux_list: List[Flux],
    vehicule: Vehicule,
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    heure_debut: int = None,
    rh: Dict[str, Any] = None,
) -> Tuple[List[StepOperation], float, float, int]:
    """
    Construit la séquence d'opérations chronologiques d'une tournée.

    Séquence pour chaque flux :
    1. Trajet vers site de départ (si nécessaire)
    2. Mise à quai au départ
    3. Chargement
    4. Trajet vers site d'arrivée
    5. Mise à quai à l'arrivée
    6. Déchargement

    Args:
        flux_list: Flux dans l'ordre de la tournée.
        vehicule: Véhicule affecté.
        sites: Dict des sites.
        contenants: Dict des contenants.
        matrix_dur: Matrice durées.
        matrix_dist: Matrice distances.
        heure_debut: Heure de début de la tournée (si None, basée sur heure dispo du 1er flux).
        rh: Paramètres RH (pour les bornes horaires).

    Returns:
        Tuple (steps, km_total, km_vide, nb_desinfections).
    """
    if not flux_list:
        return [], 0.0, 0.0, 0

    if heure_debut is None:
        heure_debut = flux_list[0].heure_dispo

    steps: List[StepOperation] = []
    heure_courante = heure_debut
    position_courante = vehicule.stationnement_initial
    etat_sanitaire = config.SANITAIRE_PROPRE
    km_total = 0.0
    km_vide = 0.0
    nb_desinfections = 0
    nb_cont_charges = 0
    surf_vehicule = vehicule.longueur * vehicule.largeur

    # Contenants actuellement chargés {type: quantité}
    cont_charges: Dict[str, int] = {}

    for flux in flux_list:
        cont = contenants.get(flux.type_contenant)
        site_dep = sites.get(flux.site_depart)
        site_arr = sites.get(flux.site_arrivee)

        # --- Vérification désinfection ---
        if etat_sanitaire == config.SANITAIRE_SALE and flux.statut_propre_sale == config.SANITAIRE_PROPRE:
            # Besoin désinfection → retour au stationnement
            if position_courante != vehicule.stationnement_initial:
                dur_ret, dist_ret = _trajet(
                    position_courante, vehicule.stationnement_initial,
                    matrix_dur, matrix_dist
                )
                est_vide = nb_cont_charges == 0
                steps.append(StepOperation(
                    heure_debut=heure_courante,
                    heure_fin=heure_courante + dur_ret,
                    type_operation=config.OP_TRAJET_VIDE if est_vide else config.OP_TRAJET_CHARGE,
                    site=vehicule.stationnement_initial,
                    distance_km=dist_ret,
                    est_trajet_vide=est_vide,
                    statut_sanitaire=etat_sanitaire,
                ))
                km_total += dist_ret
                if est_vide:
                    km_vide += dist_ret
                heure_courante += dur_ret
                position_courante = vehicule.stationnement_initial

            steps.append(StepOperation(
                heure_debut=heure_courante,
                heure_fin=heure_courante + config.DESINFECTION_DURATION,
                type_operation=config.OP_DESINFECTION,
                site=vehicule.stationnement_initial,
                statut_sanitaire=config.SANITAIRE_PROPRE,
                commentaire=f"Désinfection avant flux propre #{flux.id_flux}",
            ))
            heure_courante += config.DESINFECTION_DURATION
            etat_sanitaire = config.SANITAIRE_PROPRE
            nb_desinfections += 1

        # --- Trajet vers site de départ ---
        if position_courante != flux.site_depart:
            dur, dist = _trajet(position_courante, flux.site_depart, matrix_dur, matrix_dist)
            est_vide = nb_cont_charges == 0
            steps.append(StepOperation(
                heure_debut=heure_courante,
                heure_fin=heure_courante + dur,
                type_operation=config.OP_TRAJET_VIDE if est_vide else config.OP_TRAJET_CHARGE,
                site=flux.site_depart,
                distance_km=dist,
                est_trajet_vide=est_vide,
                statut_sanitaire=etat_sanitaire,
                flux_ids=[flux.id_flux],
            ))
            km_total += dist
            if est_vide:
                km_vide += dist
            heure_courante += dur
            position_courante = flux.site_depart

        # Respect heure de mise à disposition
        if heure_courante < flux.heure_dispo:
            # Attente
            steps.append(StepOperation(
                heure_debut=heure_courante,
                heure_fin=flux.heure_dispo,
                type_operation=config.OP_ATTENTE,
                site=flux.site_depart,
                statut_sanitaire=etat_sanitaire,
                commentaire=f"Attente disponibilité flux #{flux.id_flux}",
            ))
            heure_courante = flux.heure_dispo

        # --- Mise à quai au départ ---
        if site_dep and site_dep.presence_quai:
            steps.append(StepOperation(
                heure_debut=heure_courante,
                heure_fin=heure_courante + vehicule.temps_mise_quai,
                type_operation=config.OP_MISE_A_QUAI,
                site=flux.site_depart,
                statut_sanitaire=etat_sanitaire,
                flux_ids=[flux.id_flux],
            ))
            heure_courante += vehicule.temps_mise_quai

        # --- Chargement ---
        manu_dep = vehicule.manu_avec_quai if (site_dep and site_dep.presence_quai) else (vehicule.manu_sans_quai or 0.0)
        dur_chargement = math.ceil(manu_dep * flux.quantite)

        nb_cont_charges += flux.quantite
        cont_charges[flux.type_contenant] = cont_charges.get(flux.type_contenant, 0) + flux.quantite
        surf_chargee = sum(
            (contenants[t].longueur * contenants[t].largeur if t in contenants else 0) * q
            for t, q in cont_charges.items()
        )
        taux_surf = (surf_chargee / surf_vehicule) if surf_vehicule > 0 else 0

        if flux.statut_propre_sale == config.SANITAIRE_SALE:
            etat_sanitaire = config.SANITAIRE_SALE

        steps.append(StepOperation(
            heure_debut=heure_courante,
            heure_fin=heure_courante + dur_chargement,
            type_operation=config.OP_CHARGEMENT,
            site=flux.site_depart,
            flux_ids=[flux.id_flux],
            nb_contenants=flux.quantite,
            type_contenant=flux.type_contenant,
            taux_remplissage_surface=round(taux_surf, 3),
            statut_sanitaire=etat_sanitaire,
        ))
        heure_courante += dur_chargement

        # --- Trajet vers site d'arrivée ---
        dur, dist = _trajet(flux.site_depart, flux.site_arrivee, matrix_dur, matrix_dist)
        steps.append(StepOperation(
            heure_debut=heure_courante,
            heure_fin=heure_courante + dur,
            type_operation=config.OP_TRAJET_CHARGE,
            site=flux.site_arrivee,
            flux_ids=[flux.id_flux],
            distance_km=dist,
            est_trajet_vide=False,
            statut_sanitaire=etat_sanitaire,
            nb_contenants=nb_cont_charges,
        ))
        km_total += dist
        heure_courante += dur
        position_courante = flux.site_arrivee

        # --- Mise à quai à l'arrivée ---
        if site_arr and site_arr.presence_quai:
            steps.append(StepOperation(
                heure_debut=heure_courante,
                heure_fin=heure_courante + vehicule.temps_mise_quai,
                type_operation=config.OP_MISE_A_QUAI,
                site=flux.site_arrivee,
                statut_sanitaire=etat_sanitaire,
                flux_ids=[flux.id_flux],
            ))
            heure_courante += vehicule.temps_mise_quai

        # --- Déchargement ---
        manu_arr = vehicule.manu_avec_quai if (site_arr and site_arr.presence_quai) else (vehicule.manu_sans_quai or 0.0)
        dur_dechargement = math.ceil(manu_arr * flux.quantite)

        nb_cont_charges -= flux.quantite
        cont_charges[flux.type_contenant] = max(0, cont_charges.get(flux.type_contenant, 0) - flux.quantite)

        # Recalcul du taux APRÈS déchargement (charge courante mise à jour)
        surf_apres = sum(
            (contenants[t].longueur * contenants[t].largeur if t in contenants else 0) * q
            for t, q in cont_charges.items()
        )
        taux_apres = (surf_apres / surf_vehicule) if surf_vehicule > 0 else 0

        steps.append(StepOperation(
            heure_debut=heure_courante,
            heure_fin=heure_courante + dur_dechargement,
            type_operation=config.OP_DECHARGEMENT,
            site=flux.site_arrivee,
            flux_ids=[flux.id_flux],
            nb_contenants=flux.quantite,
            type_contenant=flux.type_contenant,
            taux_remplissage_surface=round(taux_apres, 3),
            statut_sanitaire=etat_sanitaire,
        ))
        heure_courante += dur_dechargement

    # --- Retour au stationnement initial ---
    if position_courante != vehicule.stationnement_initial:
        dur, dist = _trajet(
            position_courante, vehicule.stationnement_initial, matrix_dur, matrix_dist
        )
        steps.append(StepOperation(
            heure_debut=heure_courante,
            heure_fin=heure_courante + dur,
            type_operation=config.OP_TRAJET_VIDE,
            site=vehicule.stationnement_initial,
            distance_km=dist,
            est_trajet_vide=True,
            statut_sanitaire=etat_sanitaire,
        ))
        km_total += dist
        km_vide += dist
        heure_courante += dur

    return steps, round(km_total, 2), round(km_vide, 2), nb_desinfections


def _trajet(
    dep: str,
    arr: str,
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
) -> Tuple[int, float]:
    """Retourne (durée_minutes, distance_km) pour un trajet dep→arr."""
    dur = int(matrix_dur.get(dep, {}).get(arr, 0))
    dist = float(matrix_dist.get(dep, {}).get(arr, 0))
    return dur, dist
