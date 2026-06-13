"""
time_windows.py — Gestion des fenêtres horaires OptiFLUX.

Calcule les temps minimaux théoriques (T_min) et détecte les flux infaisables
avant lancement de l'optimisation.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple

import config
from models import Flux, Vehicule, Site


def minutes_to_hhmm(minutes: int) -> str:
    """
    Convertit un entier de minutes depuis minuit en chaîne 'HH:MM'.

    Args:
        minutes: Entier de minutes (ex. 390).

    Returns:
        Chaîne formatée 'HH:MM' (ex. '06:30').

    Example:
        >>> minutes_to_hhmm(390)
        '06:30'
    """
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def hhmm_to_minutes(hhmm: str) -> int:
    """
    Convertit une chaîne 'HH:MM' en entier de minutes depuis minuit.

    Args:
        hhmm: Chaîne au format 'HH:MM'.

    Returns:
        Entier de minutes.

    Example:
        >>> hhmm_to_minutes('06:30')
        390
    """
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def calcul_t_min(
    flux: Flux,
    vehicule: Vehicule,
    sites: Dict[str, Site],
    matrix_dur: Dict[str, Dict[str, float]],
    circulation_factor: float = 0.0,
) -> int:
    """
    Calcule le temps minimal théorique pour exécuter un flux (T_min).

    Formule :
        T_min = mise_à_quai(départ) + chargement + trajet × (1 + facteur) +
                mise_à_quai(arrivée) + déchargement

    Args:
        flux: Flux à vérifier.
        vehicule: Véhicule compatible (le plus rapide/petit acceptable).
        sites: Dict des sites.
        matrix_dur: Matrice des durées en minutes.
        circulation_factor: Facteur de circulation en % (0 = pas de correction).

    Returns:
        T_min en minutes entières.
    """
    site_dep = sites.get(flux.site_depart)
    site_arr = sites.get(flux.site_arrivee)

    # Temps de mise à quai
    quai_dep = vehicule.temps_mise_quai if (site_dep and site_dep.presence_quai) else 0
    quai_arr = vehicule.temps_mise_quai if (site_arr and site_arr.presence_quai) else 0

    # Temps de manutention par contenant
    manu_dep = _get_manu(vehicule, site_dep)
    manu_arr = _get_manu(vehicule, site_arr)

    # Les manu sont en min/contenant (float) → produit float, arrondi global en fin
    chargement = manu_dep * flux.quantite
    dechargement = manu_arr * flux.quantite

    # Temps de trajet avec facteur circulation
    trajet_brut = matrix_dur.get(flux.site_depart, {}).get(flux.site_arrivee, 0.0)
    if trajet_brut > 0:
        trajet = round(trajet_brut * (1 + circulation_factor / 100))
    else:
        trajet = 0  # sites côte à côte, durée reste 0

    total = quai_dep + chargement + trajet + quai_arr + dechargement
    # Arrondi au plafond : T_min est un majorant conservateur (jamais sous-estimé)
    return math.ceil(total)


def _get_manu(vehicule: Vehicule, site: Optional[Site]) -> float:
    """
    Retourne le temps de manutention en min/contenant (float) selon la présence de quai.

    Les valeurs sont issues du fichier Excel en secondes/contenant, converties en
    minutes flottantes par seconds_to_float_minutes() lors de l'import.
    """
    if site is None:
        return 0.0
    if site.presence_quai:
        return vehicule.manu_avec_quai
    else:
        return vehicule.manu_sans_quai or 0.0


def _detail_t_min(
    flux: Flux,
    vehicule: Vehicule,
    sites: Dict[str, Site],
    matrix_dur: Dict[str, Dict[str, float]],
    circulation_factor: float = 0.0,
) -> Dict[str, Any]:
    """Retourne le détail complet du calcul T_min pour un flux/véhicule."""
    site_dep = sites.get(flux.site_depart)
    site_arr = sites.get(flux.site_arrivee)

    quai_dep = vehicule.temps_mise_quai if (site_dep and site_dep.presence_quai) else 0
    quai_arr = vehicule.temps_mise_quai if (site_arr and site_arr.presence_quai) else 0
    manu_dep = _get_manu(vehicule, site_dep)
    manu_arr = _get_manu(vehicule, site_arr)

    trajet_brut = matrix_dur.get(flux.site_depart, {}).get(flux.site_arrivee, 0.0)
    trajet = round(trajet_brut * (1 + circulation_factor / 100)) if trajet_brut > 0 else 0

    chargement = manu_dep * flux.quantite
    dechargement = manu_arr * flux.quantite
    total = quai_dep + chargement + trajet + quai_arr + dechargement

    return {
        "vehicule": vehicule.type_vehicule,
        "quai_dep_min": quai_dep,
        "manu_dep_min_cont": round(manu_dep, 4),
        "chargement_min": round(chargement, 2),
        "trajet_min": trajet,
        "quai_arr_min": quai_arr,
        "manu_arr_min_cont": round(manu_arr, 4),
        "dechargement_min": round(dechargement, 2),
        "t_min_total": math.ceil(total),
        "detail_formule": (
            f"quai_dep({quai_dep}) + charg({round(manu_dep,3)}×{flux.quantite}={round(chargement,1)}) + "
            f"trajet({trajet}) + quai_arr({quai_arr}) + decharg({round(manu_arr,3)}×{flux.quantite}={round(dechargement,1)}) "
            f"= {math.ceil(total)} min"
        ),
    }


def detecter_flux_infaisables(
    flux_actifs: List[Flux],
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    matrix_dur: Dict[str, Dict[str, float]],
    circulation_factor: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Détecte les flux dont la fenêtre horaire est insuffisante.

    Pour chaque flux, calcule T_min avec le véhicule compatible le plus favorable.
    Retourne le détail complet du calcul pour chaque infaisable.
    """
    from compatibility import get_vehicules_compatibles_flux

    infaisables = []
    for flux in flux_actifs:
        compat_types = get_vehicules_compatibles_flux(flux, vehicules, sites)
        fenetre = flux.heure_max_livraison - flux.heure_dispo

        if not compat_types:
            # Diagnostiquer la raison de l'incompatibilité
            raison_detail = _diagnostiquer_incompatibilite(flux, vehicules, sites)
            infaisables.append({
                "id_flux": flux.id_flux,
                "site_depart": flux.site_depart,
                "site_arrivee": flux.site_arrivee,
                "quantite": flux.quantite,
                "t_min": -1,
                "fenetre_disponible": fenetre,
                "ecart": -1,
                "fenetre_min_requise": -1,
                "heure_dispo_str": minutes_to_hhmm(flux.heure_dispo),
                "heure_max_str": minutes_to_hhmm(flux.heure_max_livraison),
                "raison": "Aucun véhicule compatible",
                "raison_detail": raison_detail,
                "detail_calcul": "",
            })
            continue

        # Trouver le T_min le plus optimiste et son détail
        t_min_best = None
        detail_best = None
        for vtype in compat_types:
            veh = vehicules[vtype]
            d = _detail_t_min(flux, veh, sites, matrix_dur, circulation_factor)
            if t_min_best is None or d["t_min_total"] < t_min_best:
                t_min_best = d["t_min_total"]
                detail_best = d

        if t_min_best is not None and t_min_best > fenetre:
            infaisables.append({
                "id_flux": flux.id_flux,
                "site_depart": flux.site_depart,
                "site_arrivee": flux.site_arrivee,
                "quantite": flux.quantite,
                "t_min": t_min_best,
                "fenetre_disponible": fenetre,
                "ecart": t_min_best - fenetre,
                "fenetre_min_requise": t_min_best,
                "heure_dispo_str": minutes_to_hhmm(flux.heure_dispo),
                "heure_max_str": minutes_to_hhmm(flux.heure_max_livraison),
                "raison": f"T_min={t_min_best} min > fenêtre={fenetre} min",
                "raison_detail": f"Véhicule le + favorable : {detail_best['vehicule']}",
                "detail_calcul": detail_best["detail_formule"],
            })

    return infaisables


def _diagnostiquer_incompatibilite(
    flux: Flux,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
) -> str:
    """Explique pourquoi aucun véhicule n'est compatible avec un flux."""
    site_dep = sites.get(flux.site_depart)
    site_arr = sites.get(flux.site_arrivee)

    if site_dep is None:
        return f"Site départ '{flux.site_depart}' absent de param Sites"
    if site_arr is None:
        return f"Site arrivée '{flux.site_arrivee}' absent de param Sites"

    raisons = []
    for vtype, veh in vehicules.items():
        if not veh.compat_contenants.get(flux.type_contenant, False):
            raisons.append(f"{vtype}:contenant_incompatible")
            continue
        for sname, site in [(flux.site_depart, site_dep), (flux.site_arrivee, site_arr)]:
            if not site.compat_vehicules.get(vtype, False):
                raisons.append(f"{vtype}:site_{sname}_incompatible")
                break
            if not site.presence_quai and veh.manu_sans_quai is None:
                raisons.append(f"{vtype}:manu_sans_quai=NC_pour_{sname}")
                break

    if raisons:
        # Synthétiser
        cont_pb = [r for r in raisons if "contenant" in r]
        site_pb = [r for r in raisons if "site_" in r]
        manu_pb = [r for r in raisons if "manu_" in r]
        parts = []
        if cont_pb:
            parts.append(f"Contenant '{flux.type_contenant}' incompatible avec {len(cont_pb)} véhicule(s)")
        if site_pb:
            parts.append(f"Site non déclaré compatible pour {len(site_pb)} véhicule(s)")
        if manu_pb:
            parts.append(f"Manutention sans quai=NC pour {len(manu_pb)} véhicule(s) compatibles")
        return " | ".join(parts)
    return "Incompatibilité inconnue"


def appliquer_facteur_circulation(
    matrix_dur: Dict[str, Dict[str, float]],
    factor: float,
) -> Dict[str, Dict[str, float]]:
    """
    Applique le facteur de circulation à toutes les durées de trajet non nulles.

    Les durées nulles (sites côte à côte) restent à 0.

    Args:
        matrix_dur: Matrice originale des durées.
        factor: Facteur en % (ex. 20 pour +20%).

    Returns:
        Nouvelle matrice avec durées corrigées.
    """
    if factor == 0:
        return matrix_dur
    corrected = {}
    multiplier = 1 + factor / 100
    for site_dep, row in matrix_dur.items():
        corrected[site_dep] = {}
        for site_arr, dur in row.items():
            corrected[site_dep][site_arr] = round(dur * multiplier) if dur > 0 else 0
    return corrected
