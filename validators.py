"""
validators.py — Contrôles de cohérence du fichier OptiFLUX.

Regroupe les vérifications bloquantes (erreurs) et non bloquantes (alertes)
réalisées après import, avant toute simulation.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import config
from models import Site, Vehicule, Contenant, Flux

logger = logging.getLogger(__name__)


def validate_all(
    rh: Dict[str, int],
    sites: Dict[str, Any],
    vehicules: Dict[str, Any],
    contenants: Dict[str, Any],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    flux_brut: List[Dict[str, Any]],
    dock_capacities: Optional[Dict[str, int]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Exécute tous les contrôles de cohérence sur les données importées.

    Args:
        rh: Paramètres RH en minutes.
        sites: Dict des sites.
        vehicules: Dict des véhicules.
        contenants: Dict des contenants.
        matrix_dur: Matrice des durées.
        matrix_dist: Matrice des distances.
        flux_brut: Liste brute des flux.
        dock_capacities: Capacités de quai (optionnel, utilise config.SITE_DOCK_OVERRIDES si absent).

    Returns:
        Dict {'errors': [...], 'warnings': [...]} avec des dicts de détail.
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    # 1. Paramètres RH cohérents
    _check_rh(rh, errors)

    # 2. Matrices carrées et couvrant les mêmes sites
    _check_matrices(matrix_dur, matrix_dist, errors)

    # 3. Stationnements initiaux des véhicules renseignés
    _check_vehicule_stationnement(vehicules, sites, errors)

    # 4. Cohérence sites/véhicules (hayon vs sites sans quai)
    _check_hayon_vs_quai(vehicules, sites, warnings)

    # 5. Flux : sites existants, contenants existants
    _check_flux_references(flux_brut, sites, contenants, matrix_dur, matrix_dist, errors)

    return {"errors": errors, "warnings": warnings}


def _check_rh(rh: Dict[str, int], errors: List) -> None:
    vac = rh.get("vacation_duration", 0)
    pause = rh.get("pause_duration", 0)
    start = rh.get("start_min", 0)
    end = rh.get("end_max", 0)
    if pause >= vac:
        errors.append({
            "type": "RH_INCOHERENT",
            "message": f"Durée de pause ({pause} min) ≥ durée de vacation ({vac} min).",
        })
    if start + vac > end:
        errors.append({
            "type": "RH_INCOHERENT",
            "message": (
                f"Heure début mini + durée vacation ({start}+{vac}={start+vac} min) "
                f"> heure fin max ({end} min)."
            ),
        })


def _check_matrices(matrix_dur, matrix_dist, errors):
    sites_dur = set(matrix_dur.keys())
    sites_dist = set(matrix_dist.keys())
    extra = sites_dur.symmetric_difference(sites_dist)
    if extra:
        errors.append({
            "type": "MATRICES_INCOHERENTES",
            "message": f"Sites présents dans une seule matrice : {sorted(extra)}",
        })
    # Vérification carrée
    for row_site, row_vals in matrix_dur.items():
        col_sites = set(row_vals.keys())
        missing = sites_dur - col_sites - {row_site}
        if missing:
            errors.append({
                "type": "MATRICE_NON_CARREE",
                "message": f"matrice Durée : site '{row_site}' manque des colonnes pour : {sorted(missing)[:5]}…",
            })
            break


def _check_vehicule_stationnement(vehicules, sites, errors):
    for vtype, vdata in vehicules.items():
        stationnement = vdata.get("stationnement_initial", "").strip()
        if not stationnement:
            errors.append({
                "type": "STATIONNEMENT_MANQUANT",
                "message": f"Véhicule '{vtype}' : stationnement initial non renseigné.",
            })
        elif stationnement not in sites:
            errors.append({
                "type": "STATIONNEMENT_INCONNU",
                "message": f"Véhicule '{vtype}' : stationnement initial '{stationnement}' non trouvé dans param Sites.",
            })


def _check_hayon_vs_quai(vehicules, sites, warnings):
    for vtype, vdata in vehicules.items():
        hayon = vdata.get("hayon", False)
        manu_sq = vdata.get("manu_sans_quai")
        for site_name, sdata in sites.items():
            if sdata.get("presence_quai", True):
                continue
            compat = sdata.get("compat_vehicules", {}).get(vtype, False)
            if compat and (not hayon or manu_sq is None):
                warnings.append({
                    "type": "CONTRADICTION_HAYON_QUAI",
                    "message": (
                        f"Site '{site_name}' (sans quai) est déclaré compatible avec '{vtype}' "
                        f"qui n'a pas de hayon ou manutention=NC. "
                        f"La colonne param Sites fait foi."
                    ),
                })


def _check_flux_references(flux_brut, sites, contenants, matrix_dur, matrix_dist, errors):
    sites_keys = set(sites.keys())
    contenants_keys = set(contenants.keys())
    matrix_sites = set(matrix_dur.keys())

    unknown_sites = set()
    unknown_matrix_sites = set()
    unknown_contenants = set()

    for f in flux_brut:
        dep = f.get("site_depart", "")
        arr = f.get("site_arrivee", "")
        cont = f.get("type_contenant", "")
        if dep and dep not in sites_keys:
            unknown_sites.add(dep)
        if arr and arr not in sites_keys:
            unknown_sites.add(arr)
        if dep and dep not in matrix_sites:
            unknown_matrix_sites.add(dep)
        if arr and arr not in matrix_sites:
            unknown_matrix_sites.add(arr)
        if cont and cont.strip() and cont not in contenants_keys:
            unknown_contenants.add(cont)

    if unknown_sites:
        errors.append({
            "type": "SITES_INCONNUS_FLUX",
            "message": f"Sites référencés dans M flux mais absents de param Sites : {sorted(unknown_sites)}",
        })
    if unknown_matrix_sites:
        errors.append({
            "type": "SITES_ABSENTS_MATRICES",
            "message": f"Sites référencés dans M flux mais absents des matrices : {sorted(unknown_matrix_sites)}",
        })
    if unknown_contenants:
        errors.append({
            "type": "CONTENANTS_INCONNUS",
            "message": f"Contenants référencés dans M flux mais absents de param Contenants : {sorted(unknown_contenants)}",
        })
