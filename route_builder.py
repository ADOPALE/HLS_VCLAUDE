"""
route_builder.py — Construction des séquences chronologiques de tournées OptiFLUX.

Deux entrées possibles :
  - build_route_from_visites(visites, ...)  ← nouvelle API VRPPDTW
    Prend une liste de VisiteSite (chaque arrêt peut charger ET décharger
    plusieurs flux simultanément). C'est l'API principale utilisée par le
    moteur VRPPDTW.

  - build_route_steps(flux_list, ...)  ← ancienne API, conservée pour
    compatibilité et pour les cas simples (flux uniques).
"""

from __future__ import annotations
import math
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from models import Flux, Vehicule, Site, Contenant, StepOperation

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# API PRINCIPALE — VRPPDTW
# ════════════════════════════════════════════════════════════════════════════

def build_route_from_visites(
    visites: List[Any],          # List[VisiteSite] — import circulaire évité
    vehicule: Vehicule,
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
) -> Tuple[List[StepOperation], float, float, int]:
    """
    Construit la séquence chronologique d'opérations à partir d'une liste de
    VisiteSite (format VRPPDTW).

    À chaque arrêt, le véhicule peut décharger puis charger plusieurs flux.
    Le déchargement est toujours effectué avant le chargement (libère de la place).

    Returns:
        (steps, km_total, km_vide, nb_desinfections)
    """
    if not visites:
        return [], 0.0, 0.0, 0

    steps: List[StepOperation] = []
    heure = _heure_debut_optimale(visites)
    position = vehicule.stationnement_initial
    etat_sanitaire = config.SANITAIRE_PROPRE

    km_total = 0.0
    km_vide = 0.0
    nb_desinfections = 0

    # Charge courante par type de contenant : {type_contenant: quantite}
    cont_charges: Dict[str, int] = {}
    surf_vehicule = vehicule.longueur * vehicule.largeur

    for visite in visites:
        site_obj = sites.get(visite.site)
        a_quai = site_obj is not None and site_obj.presence_quai
        manu = (vehicule.manu_avec_quai if a_quai else (vehicule.manu_sans_quai or 0.0))

        # ── Désinfection (sale → propre) avant cet arrêt ─────────────────
        # Nécessaire si le véhicule est sale ET qu'on va charger du propre ici
        besoin_desinf = (
            etat_sanitaire == config.SANITAIRE_SALE
            and any(f.statut_propre_sale == config.SANITAIRE_PROPRE
                    for f in visite.flux_charges)
            and not any(f.transport_mixte for f in visite.flux_charges)
        )
        if besoin_desinf:
            # Retour au stationnement pour désinfection si pas déjà là
            if position != vehicule.stationnement_initial:
                dur_ret, dist_ret = _trajet(
                    position, vehicule.stationnement_initial, matrix_dur, matrix_dist
                )
                est_vide = sum(cont_charges.values()) == 0
                steps.append(StepOperation(
                    heure_debut=heure, heure_fin=heure + dur_ret,
                    type_operation=config.OP_TRAJET_VIDE if est_vide else config.OP_TRAJET_CHARGE,
                    site=vehicule.stationnement_initial,
                    distance_km=dist_ret, est_trajet_vide=est_vide,
                    statut_sanitaire=etat_sanitaire,
                ))
                km_total += dist_ret
                if est_vide:
                    km_vide += dist_ret
                heure += dur_ret
                position = vehicule.stationnement_initial

            steps.append(StepOperation(
                heure_debut=heure, heure_fin=heure + config.DESINFECTION_DURATION,
                type_operation=config.OP_DESINFECTION,
                site=vehicule.stationnement_initial,
                statut_sanitaire=config.SANITAIRE_PROPRE,
                commentaire="Désinfection avant chargement propre",
            ))
            heure += config.DESINFECTION_DURATION
            etat_sanitaire = config.SANITAIRE_PROPRE
            nb_desinfections += 1

        # ── Trajet vers le site ───────────────────────────────────────────
        if position != visite.site:
            dur, dist = _trajet(position, visite.site, matrix_dur, matrix_dist)
            est_vide = sum(cont_charges.values()) == 0
            steps.append(StepOperation(
                heure_debut=heure, heure_fin=heure + dur,
                type_operation=config.OP_TRAJET_VIDE if est_vide else config.OP_TRAJET_CHARGE,
                site=visite.site,
                distance_km=dist, est_trajet_vide=est_vide,
                statut_sanitaire=etat_sanitaire,
                flux_ids=[f.id_flux for f in visite.flux_charges + visite.flux_decharges],
            ))
            km_total += dist
            if est_vide:
                km_vide += dist
            heure += dur
            position = visite.site

        # ── Attente si flux pas encore disponibles ────────────────────────
        if visite.flux_charges:
            heure_min_dispo = min(f.heure_dispo for f in visite.flux_charges)
            if heure < heure_min_dispo:
                steps.append(StepOperation(
                    heure_debut=heure, heure_fin=heure_min_dispo,
                    type_operation=config.OP_ATTENTE,
                    site=visite.site, statut_sanitaire=etat_sanitaire,
                    commentaire=f"Attente disponibilité ({len(visite.flux_charges)} flux)",
                ))
                heure = heure_min_dispo

        # ── Mise à quai (une seule fois par arrêt) ────────────────────────
        if a_quai and (visite.flux_charges or visite.flux_decharges):
            steps.append(StepOperation(
                heure_debut=heure, heure_fin=heure + vehicule.temps_mise_quai,
                type_operation=config.OP_MISE_A_QUAI,
                site=visite.site, statut_sanitaire=etat_sanitaire,
                flux_ids=[f.id_flux for f in visite.flux_charges + visite.flux_decharges],
            ))
            heure += vehicule.temps_mise_quai

        # ── Déchargements ─────────────────────────────────────────────────
        for flux in visite.flux_decharges:
            dur_dech = math.ceil(manu * flux.quantite)
            cont_charges[flux.type_contenant] = max(
                0, cont_charges.get(flux.type_contenant, 0) - flux.quantite
            )
            surf_chargee = _surf_chargee(cont_charges, contenants)
            taux = _taux_chargement(cont_charges, contenants, vehicule)

            steps.append(StepOperation(
                heure_debut=heure, heure_fin=heure + dur_dech,
                type_operation=config.OP_DECHARGEMENT,
                site=visite.site,
                flux_ids=[flux.id_flux],
                nb_contenants=flux.quantite,
                type_contenant=flux.type_contenant,
                taux_remplissage_surface=round(taux, 3),
                statut_sanitaire=etat_sanitaire,
            ))
            heure += dur_dech

        # ── Chargements ───────────────────────────────────────────────────
        for flux in visite.flux_charges:
            dur_ch = math.ceil(manu * flux.quantite)

            # Mise à jour état sanitaire
            if flux.statut_propre_sale == config.SANITAIRE_SALE:
                etat_sanitaire = config.SANITAIRE_SALE

            cont_charges[flux.type_contenant] = (
                cont_charges.get(flux.type_contenant, 0) + flux.quantite
            )
            surf_chargee = _surf_chargee(cont_charges, contenants)
            taux = _taux_chargement(cont_charges, contenants, vehicule)

            steps.append(StepOperation(
                heure_debut=heure, heure_fin=heure + dur_ch,
                type_operation=config.OP_CHARGEMENT,
                site=visite.site,
                flux_ids=[flux.id_flux],
                nb_contenants=flux.quantite,
                type_contenant=flux.type_contenant,
                taux_remplissage_surface=round(taux, 3),
                statut_sanitaire=etat_sanitaire,
            ))
            heure += dur_ch

    # ── Retour au stationnement initial ───────────────────────────────────
    if position != vehicule.stationnement_initial:
        dur, dist = _trajet(
            position, vehicule.stationnement_initial, matrix_dur, matrix_dist
        )
        est_vide = sum(cont_charges.values()) == 0
        steps.append(StepOperation(
            heure_debut=heure, heure_fin=heure + dur,
            type_operation=config.OP_TRAJET_VIDE,
            site=vehicule.stationnement_initial,
            distance_km=dist, est_trajet_vide=True,
            statut_sanitaire=etat_sanitaire,
        ))
        km_total += dist
        km_vide += dist
        heure += dur

    return steps, round(km_total, 2), round(km_vide, 2), nb_desinfections


# ════════════════════════════════════════════════════════════════════════════
# API LEGACY — liste de flux séquentiels
# ════════════════════════════════════════════════════════════════════════════

def build_route_steps(
    flux_list: List[Flux],
    vehicule: Vehicule,
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    heure_debut: Optional[int] = None,
    rh: Optional[Dict[str, Any]] = None,
) -> Tuple[List[StepOperation], float, float, int]:
    """
    Convertit une liste de flux en VisiteSite et délègue à build_route_from_visites.
    Chaque flux génère 2 visites : charge au site_depart, décharge au site_arrivee.
    """
    if not flux_list:
        return [], 0.0, 0.0, 0

    # Construire les VisiteSite : regrouper par site dans l'ordre
    # (charge + décharge au même site si flux se croisent)
    from optimizer import VisiteSite

    # Construire la séquence dans l'ordre des flux
    visites_dict: Dict[str, "VisiteSite"] = {}
    sequence: List["VisiteSite"] = []

    for flux in flux_list:
        # Visite de départ (charge)
        key_dep = f"{flux.site_depart}_{flux.id_flux}_dep"
        v_dep = VisiteSite(site=flux.site_depart, flux_charges=[flux])
        sequence.append(v_dep)

        # Visite d'arrivée (décharge)
        v_arr = VisiteSite(site=flux.site_arrivee, flux_decharges=[flux])
        sequence.append(v_arr)

    return build_route_from_visites(
        sequence, vehicule, sites, contenants, matrix_dur, matrix_dist
    )


# ════════════════════════════════════════════════════════════════════════════
# UTILITAIRES
# ════════════════════════════════════════════════════════════════════════════

def _trajet(
    dep: str,
    arr: str,
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
) -> Tuple[int, float]:
    """Retourne (durée_min, distance_km) pour un trajet dep→arr."""
    dur = int(matrix_dur.get(dep, {}).get(arr, 0))
    dist = float(matrix_dist.get(dep, {}).get(arr, 0))
    return dur, dist


def _surf_chargee(
    cont_charges: Dict[str, int],
    contenants: Dict[str, Contenant],
) -> float:
    """Surface physique chargée (m²) — pour affichage brut."""
    return sum(
        (contenants[t].longueur * contenants[t].largeur if t in contenants else 0) * q
        for t, q in cont_charges.items()
    )


def _taux_chargement(
    cont_charges: Dict[str, int],
    contenants: Dict[str, Contenant],
    vehicule: Any,
) -> float:
    """
    Taux d'utilisation du véhicule, calculé sur la capacité discrète de chaque
    type de contenant (floor(L_veh/L_cont) × floor(l_veh/l_cont)).

    Pour les chargements MONO-type : taux ≤ 1.0 toujours.
    Pour les chargements MIXTES   : le taux est la somme pondérée des fractions
    de capacité de chaque contenant ; peut légèrement dépasser 1.0 si le modèle
    surfacique discret ne peut pas calculer le packing 2D combiné exact.
    """
    from capacity import max_contenants_par_vehicule
    total = 0.0
    for cont_type, qty in cont_charges.items():
        if qty <= 0:
            continue
        cont = contenants.get(cont_type)
        if cont is None:
            continue
        cap = max_contenants_par_vehicule(vehicule, cont)
        if cap > 0:
            total += qty / cap
    return total


def _heure_debut_optimale(visites: List[Any]) -> int:
    """Heure de début : la plus tôt parmi tous les flux à charger."""
    heures = []
    for v in visites:
        for f in getattr(v, "flux_charges", []):
            heures.append(f.heure_dispo)
    if not heures:
        return config.DEFAULT_RH["start_min"]
    return min(heures)
