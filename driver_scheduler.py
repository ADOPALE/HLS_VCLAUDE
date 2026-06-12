"""
driver_scheduler.py — Affectation des postes chauffeurs OptiFLUX.

Calcule les postes de travail à partir des tournées, en respectant :
- Durée exacte de vacation
- Pause au milieu ±1h au stationnement initial
- Prise de poste (15 min) et fin de poste (10 min)
- Changement de chauffeur au stationnement initial uniquement
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import config
from models import Tournee, PosteChaufeur, StepOperation, Vehicule

logger = logging.getLogger(__name__)


def affecter_postes(
    tournees: List[Tournee],
    vehicules: Dict[str, Vehicule],
    rh: Dict[str, int],
) -> List[PosteChaufeur]:
    """
    Affecte les tournées à des postes chauffeurs en respectant les contraintes RH.

    Chaque véhicule peut avoir 1 ou 2 postes dans la journée.
    Les postes durent exactement la durée de vacation.
    La pause est positionnée dans la fenêtre ±1h autour du milieu du poste.

    Args:
        tournees: Liste des tournées calculées par l'optimiseur.
        vehicules: Dict des véhicules.
        rh: Paramètres RH {vacation_duration, pause_duration, start_min, end_max}.

    Returns:
        Liste de PosteChaufeur.
    """
    vacation = rh["vacation_duration"]
    pause_dur = rh["pause_duration"]
    start_min = rh["start_min"]
    end_max = rh["end_max"]

    # Grouper les tournées par véhicule
    tournees_par_veh: Dict[str, List[Tournee]] = {}
    for t in tournees:
        tournees_par_veh.setdefault(t.type_vehicule, []).append(t)

    postes: List[PosteChaufeur] = []
    poste_id = 1

    for vtype, t_list in tournees_par_veh.items():
        veh = vehicules.get(vtype)
        if not veh:
            continue

        # Trier les tournées par heure de début
        t_list.sort(key=lambda t: t.heure_debut)

        # Calculer le début optimal du 1er poste
        premier_debut = max(start_min, t_list[0].heure_debut - config.PRISE_DE_POSTE_MIN)
        # Arrondir à start_min si possible
        if premier_debut < start_min:
            premier_debut = start_min

        poste_debut = premier_debut
        poste_fin = poste_debut + vacation

        if poste_fin > end_max:
            # Pas de place pour ce poste → ajuster
            poste_debut = end_max - vacation
            poste_fin = end_max

        # Poste 1
        poste1 = _creer_poste(
            poste_id=poste_id,
            numero=1,
            vtype=vtype,
            veh=veh,
            debut=poste_debut,
            fin=poste_fin,
            vacation=vacation,
            pause_dur=pause_dur,
            tournees=[t for t in t_list if t.heure_debut < poste_fin],
        )
        postes.append(poste1)
        poste_id += 1

        # Poste 2 si nécessaire et possible
        tournees_restantes = [t for t in t_list if t.heure_debut >= poste_fin]
        if tournees_restantes:
            debut2 = poste_fin
            fin2 = debut2 + vacation
            if fin2 <= end_max:
                poste2 = _creer_poste(
                    poste_id=poste_id,
                    numero=2,
                    vtype=vtype,
                    veh=veh,
                    debut=debut2,
                    fin=fin2,
                    vacation=vacation,
                    pause_dur=pause_dur,
                    tournees=tournees_restantes,
                )
                postes.append(poste2)
                poste_id += 1

    return postes


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
    """Crée un poste chauffeur avec séquence d'opérations."""
    steps: List[StepOperation] = []
    heure = debut
    temps_conduite = 0
    temps_manutention = 0
    temps_quai_total = 0
    temps_desinfection = 0
    temps_attente = 0

    # Prise de poste
    steps.append(StepOperation(
        heure_debut=heure,
        heure_fin=heure + config.PRISE_DE_POSTE_MIN,
        type_operation=config.OP_PRISE_POSTE,
        site=veh.stationnement_initial,
    ))
    heure += config.PRISE_DE_POSTE_MIN

    # Milieu du poste pour positionnement de la pause
    milieu_poste = debut + vacation // 2
    pause_window_start = milieu_poste - config.PAUSE_WINDOW_HOURS
    pause_window_end = milieu_poste + config.PAUSE_WINDOW_HOURS
    pause_insere = False

    # Intégrer les opérations des tournées
    for t in tournees:
        for step in t.steps:
            # Insérer pause si on est dans la fenêtre et au stationnement initial
            if (not pause_insere
                    and step.site == veh.stationnement_initial
                    and pause_window_start <= heure <= pause_window_end):
                steps.append(StepOperation(
                    heure_debut=heure,
                    heure_fin=heure + pause_dur,
                    type_operation=config.OP_PAUSE,
                    site=veh.stationnement_initial,
                ))
                heure += pause_dur
                pause_insere = True

            adj_step = StepOperation(
                heure_debut=heure,
                heure_fin=heure + (step.heure_fin - step.heure_debut),
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
            dur = step.heure_fin - step.heure_debut
            steps.append(adj_step)
            heure += dur

            # Accumulation des temps
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

    # Pause si pas encore insérée
    if not pause_insere:
        steps.append(StepOperation(
            heure_debut=heure,
            heure_fin=heure + pause_dur,
            type_operation=config.OP_PAUSE,
            site=veh.stationnement_initial,
        ))
        heure += pause_dur

    # Temps inoccupé avant fin de poste
    temps_inoccupe = max(0, fin - config.FIN_DE_POSTE_MIN - heure)
    if temps_inoccupe > 0:
        steps.append(StepOperation(
            heure_debut=heure,
            heure_fin=heure + temps_inoccupe,
            type_operation=config.OP_INOCCUPE,
            site=veh.stationnement_initial,
        ))
        heure += temps_inoccupe

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
