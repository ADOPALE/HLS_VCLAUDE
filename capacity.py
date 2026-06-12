"""
capacity.py — Calcul de capacité véhicule OptiFLUX.

Gestion de la capacité surfacique 2D (avec rotation des contenants)
et de la contrainte de poids. Aucun calcul de hauteur (non fourni).
"""

from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple

from models import Vehicule, Contenant, Flux


def max_contenants_par_vehicule(
    vehicule: Vehicule,
    contenant: Contenant,
) -> int:
    """
    Calcule le nombre maximum de contenants d'un type donné dans un véhicule,
    en utilisant le remplissage surfacique 2D avec test des deux orientations.

    Principe : aire plancher / aire contenant, les deux orientations du contenant
    sont testées et l'orientation la plus favorable est retenue.

    La contrainte de poids est traitée séparément dans check_poids_ok().

    Args:
        vehicule: Modèle Vehicule.
        contenant: Modèle Contenant.

    Returns:
        Nombre entier de contenants pouvant tenir dans le véhicule.

    Example:
        >>> max_contenants_par_vehicule(vehicule_pl19t, contenant_roll)
        12
    """
    surf_vehicule = vehicule.longueur * vehicule.largeur
    if surf_vehicule <= 0:
        return 0
    if contenant.longueur <= 0 or contenant.largeur <= 0:
        return 0

    # Orientation 1 : longueur × largeur
    surf1 = contenant.longueur * contenant.largeur
    # Orientation 2 : largeur × longueur (rotation 90°)
    surf2 = contenant.largeur * contenant.longueur  # identique mathématiquement
    # Essai avec colonnes entières (arrangement en grille)
    n1 = _grid_capacity(vehicule.longueur, vehicule.largeur, contenant.longueur, contenant.largeur)
    n2 = _grid_capacity(vehicule.longueur, vehicule.largeur, contenant.largeur, contenant.longueur)

    return max(n1, n2)


def _grid_capacity(veh_l: float, veh_w: float, cont_l: float, cont_w: float) -> int:
    """
    Calcule le nombre de contenants en arrangement rectangulaire.

    Args:
        veh_l, veh_w: Dimensions du véhicule.
        cont_l, cont_w: Dimensions du contenant (orientation donnée).

    Returns:
        Nombre de contenants.
    """
    if cont_l <= 0 or cont_w <= 0:
        return 0
    cols = math.floor(veh_l / cont_l)
    rows = math.floor(veh_w / cont_w)
    return cols * rows


def check_poids_ok(
    vehicule: Vehicule,
    contenants_charges: List[Tuple[Contenant, int, bool]],
) -> bool:
    """
    Vérifie que le poids total chargé ne dépasse pas la capacité du véhicule.

    Args:
        vehicule: Modèle Vehicule.
        contenants_charges: Liste de tuples (contenant, quantité, est_plein).

    Returns:
        True si contrainte poids respectée.
    """
    poids_total = sum(
        (cont.poids_plein if est_plein else cont.poids_vide) * qty
        for cont, qty, est_plein in contenants_charges
    )
    return poids_total <= vehicule.poids_max


def taux_remplissage_surface(
    vehicule: Vehicule,
    contenants_charges: List[Tuple[Contenant, int]],
) -> float:
    """
    Calcule le taux de remplissage surfacique courant [0, 1].

    Args:
        vehicule: Modèle Vehicule.
        contenants_charges: Liste de tuples (contenant, quantité).

    Returns:
        Taux de remplissage entre 0 et 1 (peut dépasser 1 en cas de sur-chargement).
    """
    surf_vehicule = vehicule.longueur * vehicule.largeur
    if surf_vehicule <= 0:
        return 0.0
    surf_chargee = sum(c.longueur * c.largeur * qty for c, qty in contenants_charges)
    return surf_chargee / surf_vehicule


def taux_remplissage_poids(
    vehicule: Vehicule,
    contenants_charges: List[Tuple[Contenant, int, bool]],
) -> float:
    """
    Calcule le taux de remplissage en poids [0, 1].

    Args:
        vehicule: Modèle Vehicule.
        contenants_charges: Liste de tuples (contenant, quantité, est_plein).

    Returns:
        Taux de remplissage entre 0 et 1.
    """
    if vehicule.poids_max <= 0:
        return 0.0
    poids = sum(
        (c.poids_plein if ep else c.poids_vide) * qty
        for c, qty, ep in contenants_charges
    )
    return min(1.0, poids / vehicule.poids_max)


def eclater_flux_volumineux(
    flux: Flux,
    vehicule: Vehicule,
    contenant: Contenant,
) -> List[Tuple[int, bool]]:
    """
    Éclate un flux dont la quantité dépasse la capacité du véhicule.

    Retourne une liste de tuples (nb_contenants, est_dernier_reste).

    Args:
        flux: Flux à transporter.
        vehicule: Véhicule le plus capacitaire compatible.
        contenant: Contenant du flux.

    Returns:
        Liste de tuples [(nb_cont, est_reste), ...]. Les premiers éléments sont
        des chargements pleins, le dernier est le reste.

    Example:
        >>> eclater_flux_volumineux(flux_170_cont, veh_pl19t_cap15, cont)
        [(15, False), (15, False), ..., (5, True)]
    """
    cap = max_contenants_par_vehicule(vehicule, contenant)
    if cap <= 0:
        cap = 1
    total = flux.quantite
    if total <= cap:
        return [(total, True)]

    n_pleins = total // cap
    reste = total % cap
    result = [(cap, False)] * n_pleins
    if reste > 0:
        result.append((reste, True))
    return result
