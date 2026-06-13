"""
driver_scheduler.py — Affectation des postes chauffeurs OptiFLUX.

1 poste = 1 vacation = 1 véhicule physique.

Algorithme :
  - Trier les tournées de chaque type de véhicule par heure de début.
  - Remplir chaque poste avec des tournées consécutives tant que le temps
    utile disponible le permet (vacation − prise_poste − fin_poste − pause).
  - Ouvrir un nouveau poste (= nouveau véhicule physique) dès qu'une tournée
    ne rentre plus.
  - Signaler une erreur de conformité si le poste dépasse end_max.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from models import Tournee, PosteChaufeur, StepOperation, Vehicule
from time_windows import minutes_to_hhmm

logger = logging.getLogger(__name__)


def affecter_postes(
    tournees: List[Tournee],
    vehicules: Dict[str, Vehicule],
    rh: Dict[str, int],
) -> Tuple[List[PosteChaufeur], List[Dict[str, Any]]]:
    """
    Affecte les tournées à des postes chauffeurs en respectant les contraintes RH.

    Args:
        tournees: Liste des tournées construites par l'optimiseur.
        vehicules: Dict des véhicules.
        rh: Paramètres RH.

    Returns:
        Tuple (postes, erreurs_conformite).
        erreurs_conformite contient les dépassements d'amplitude horaire.
    """
    vacation = rh["vacation_duration"]
    pause_dur = rh["pause_duration"]
    start_min = rh["start_min"]
    end_max = rh["end_max"]

    # Temps utile disponible par poste (hors overhead fixe)
    overhead = config.PRISE_DE_POSTE_MIN + config.FIN_DE_POSTE_MIN + pause_dur
    max_utile = max(0, vacation - overhead)

    # Grouper les tournées par type de véhicule
    par_veh: Dict[str, List[Tournee]] = {}
    for t in tournees:
        par_veh.setdefault(t.type_vehicule, []).append(t)

    postes: List[PosteChaufeur] = []
    erreurs: List[Dict[str, Any]] = []
    poste_id = 1

    for vtype, t_list in par_veh.items():
        veh = vehicules.get(vtype)
        if not veh:
            continue

        # Tri par heure de début
        t_list.sort(key=lambda t: t.heure_debut)

        # Remplissage glouton des postes
        pending = list(t_list)
        num_poste = 1

        while pending:
            panier: List[Tournee] = []
            temps_utile = 0

            # Remplir le poste avec des tournées consécutives
            for t in pending:
                dur = t.heure_fin - t.heure_debut
                if temps_utile + dur <= max_utile:
                    panier.append(t)
                    temps_utile += dur
                else:
                    break  # Arrêt dès que la prochaine ne rentre plus

            # Forcer au moins une tournée (même si elle dépasse seule)
            if not panier:
                panier = [pending[0]]

            pending = pending[len(panier):]

            # Calcul des bornes du poste
            premier_debut = panier[0].heure_debut
            poste_debut = max(start_min, premier_debut - config.PRISE_DE_POSTE_MIN)
            poste_fin = poste_debut + vacation

            # Vérification amplitude
            if poste_fin > end_max:
                erreurs.append({
                    "type": "AMPLITUDE_DEPASSEE",
                    "statut": "ERREUR",
                    "detail": (
                        f"{vtype} — poste #{num_poste} : "
                        f"fin estimée {minutes_to_hhmm(poste_fin)} > "
                        f"fin max {minutes_to_hhmm(end_max)}"
                    ),
                    "concerne": vtype,
                    "gravite": "CRITIQUE",
                    "action": (
                        "Augmenter le nombre de véhicules de ce type "
                        "ou élargir la plage horaire."
                    ),
                })

            poste = _creer_poste(
                poste_id=poste_id,
                numero=num_poste,
                vtype=vtype,
                veh=veh,
                debut=poste_debut,
                fin=poste_fin,
                vacation=vacation,
                pause_dur=pause_dur,
                tournees=panier,
            )
            postes.append(poste)
            poste_id += 1
            num_poste += 1

    return postes, erreurs


def _creer_poste(
    poste_id: int,
    numero: int,
    vtype: str,
    veh: Vehicule,
    debut: int,
    fin: int,
    vacation: int,
    pause_dur: int,
    tournees: List[Tournee],
) -> PosteChaufeur:
    """
    Crée un poste chauffeur avec la séquence d'opérations.

    Séquence :
    1. Prise de poste au stationnement initial
    2. Pour chaque tournée : toutes ses étapes (ajustées dans le temps)
       La pause est insérée dès que possible dans la fenêtre ±1h autour
       du milieu du poste, quand le véhicule est au stationnement initial.
    3. Temps inoccupé éventuel
    4. Fin de poste
    """
    steps: List[StepOperation] = []
    heure = debut

    # Compteurs de temps
    temps_conduite = 0
    temps_manutention = 0
    temps_quai_total = 0
    temps_desinfection = 0
    temps_attente = 0
    temps_inoccupe = 0

    # Prise de poste
    steps.append(StepOperation(
        heure_debut=heure,
        heure_fin=heure + config.PRISE_DE_POSTE_MIN,
        type_operation=config.OP_PRISE_POSTE,
        site=veh.stationnement_initial,
    ))
    heure += config.PRISE_DE_POSTE_MIN

    # Fenêtre de pause (±1h autour du milieu du poste)
    milieu = debut + vacation // 2
    pause_window_start = milieu - config.PAUSE_WINDOW_HOURS
    pause_window_end = milieu + config.PAUSE_WINDOW_HOURS
    pause_inseree = False

    # Intégrer les étapes de chaque tournée
    for tournee in tournees:
        for step in tournee.steps:
            dur = step.heure_fin - step.heure_debut
            if dur <= 0:
                continue

            # Insérer la pause si on est dans la fenêtre et au stationnement
            if (
                not pause_inseree
                and step.site == veh.stationnement_initial
                and pause_window_start <= heure <= pause_window_end
            ):
                steps.append(StepOperation(
                    heure_debut=heure,
                    heure_fin=heure + pause_dur,
                    type_operation=config.OP_PAUSE,
                    site=veh.stationnement_initial,
                ))
                heure += pause_dur
                pause_inseree = True

            adj = StepOperation(
                heure_debut=heure,
                heure_fin=heure + dur,
                type_operation=step.type_operation,
                site=step.site,
                flux_ids=step.flux_ids,
                nb_contenants=step.nb_contenants,
                type_contenant=step.type_contenant,
                taux_remplissage_surface=step.taux_remplissage_surface,
                statut_sanitaire=step.statut_sanitaire,
                distance_km=step.distance_km,
                est_trajet_vide=step.est_trajet_vide,
                commentaire=step.commentaire,
            )
            steps.append(adj)
            heure += dur

            if step.type_operation in (config.OP_TRAJET_VIDE, config.OP_TRAJET_CHARGE):
                temps_conduite += dur
            elif step.type_operation in (config.OP_CHARGEMENT, config.OP_DECHARGEMENT):
                temps_manutention += dur
            elif step.type_operation == config.OP_MISE_A_QUAI:
                temps_quai_total += dur
            elif step.type_operation == config.OP_DESINFECTION:
                temps_desinfection += dur
            elif step.type_operation == config.OP_ATTENTE:
                temps_attente += dur

    # Pause hors fenêtre si non insérée
    if not pause_inseree:
        steps.append(StepOperation(
            heure_debut=heure,
            heure_fin=heure + pause_dur,
            type_operation=config.OP_PAUSE,
            site=veh.stationnement_initial,
        ))
        heure += pause_dur

    # Temps inoccupé avant fin de poste
    fin_travail = fin - config.FIN_DE_POSTE_MIN
    if heure < fin_travail:
        temps_inoccupe = fin_travail - heure
        steps.append(StepOperation(
            heure_debut=heure,
            heure_fin=fin_travail,
            type_operation=config.OP_INOCCUPE,
            site=veh.stationnement_initial,
        ))
        heure = fin_travail

    # Fin de poste
    steps.append(StepOperation(
        heure_debut=heure,
        heure_fin=fin,
        type_operation=config.OP_FIN_POSTE,
        site=veh.stationnement_initial,
    ))

    return PosteChaufeur(
        id_poste=poste_id,
        numero_poste=numero,
        type_vehicule=vtype,
        heure_debut=debut,
        heure_fin=fin,
        duree_vacation=vacation,
        tournees=[t.id_tournee for t in tournees],
        steps=steps,
        temps_prise_poste=config.PRISE_DE_POSTE_MIN,
        temps_fin_poste=config.FIN_DE_POSTE_MIN,
        temps_pause=pause_dur,
        temps_conduite=temps_conduite,
        temps_manutention=temps_manutention,
        temps_quai=temps_quai_total,
        temps_desinfection=temps_desinfection,
        temps_attente=temps_attente,
        temps_inoccupe=temps_inoccupe,
        nb_desinfections=sum(
            1 for s in steps if s.type_operation == config.OP_DESINFECTION
        ),
    )
