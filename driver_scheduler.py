"""
driver_scheduler.py — Affectation des postes chauffeurs OptiFLUX.

Architecture :
  - 1 véhicule physique peut avoir 2 postes (quart du matin + quart de l'après-midi)
    sur le même engin, avec 2 chauffeurs différents.
  - Le greedy packing utilise le temps effectif absolu (incluant l'attente entre
    tournées) pour éviter les dépassements d'amplitude.
  - Une désinfection est automatiquement insérée entre tournées quand le véhicule
    passe d'un état Sale à un état Propre.
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
    Affecte les tournées à des postes chauffeurs.

    Chaque véhicule physique peut avoir jusqu'à 2 postes (2 quarts).
    Le 2ème quart commence exactement quand le 1er se termine sur le même engin.

    Returns:
        (postes, erreurs_conformite)
    """
    vacation = rh["vacation_duration"]
    pause_dur = rh["pause_duration"]
    start_min = rh["start_min"]
    end_max = rh["end_max"]

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

        t_list.sort(key=lambda t: t.heure_debut)
        pending = list(t_list)

        while pending:
            # ── Quart 1 ────────────────────────────────────────────────────
            first_t = pending[0]
            debut1 = max(start_min, first_t.heure_debut - config.PRISE_DE_POSTE_MIN)
            fin1 = debut1 + vacation

            quart1, remaining = _remplir_quart(pending, debut1, fin1, vacation, pause_dur)
            if not quart1:
                quart1 = [pending[0]]
                remaining = pending[1:]

            if fin1 > end_max:
                erreurs.append(_erreur_amplitude(vtype, 1, fin1, end_max))

            postes.append(_creer_poste(
                poste_id=poste_id, numero=1, vtype=vtype, veh=veh,
                debut=debut1, fin=fin1, vacation=vacation, pause_dur=pause_dur,
                tournees=quart1,
            ))
            poste_id += 1

            # ── Quart 2 (même véhicule physique, 2ème chauffeur) ──────────
            # Éligibles : tournées dont le début réel est ≥ fin du quart 1
            eligible_q2 = [t for t in remaining if t.heure_debut >= fin1]
            needs_parallel = [t for t in remaining if t.heure_debut < fin1]

            if eligible_q2 and fin1 + vacation <= end_max:
                debut2 = fin1
                fin2 = debut2 + vacation

                quart2, remaining_q2 = _remplir_quart(eligible_q2, debut2, fin2, vacation, pause_dur)

                if quart2:
                    if fin2 > end_max:
                        erreurs.append(_erreur_amplitude(vtype, 2, fin2, end_max))

                    postes.append(_creer_poste(
                        poste_id=poste_id, numero=2, vtype=vtype, veh=veh,
                        debut=debut2, fin=fin2, vacation=vacation, pause_dur=pause_dur,
                        tournees=quart2,
                    ))
                    poste_id += 1
                    pending = needs_parallel + remaining_q2 + eligible_q2[len(quart2):]
                else:
                    pending = needs_parallel + eligible_q2
            else:
                pending = needs_parallel + eligible_q2

    return postes, erreurs


def _remplir_quart(
    tournees: List[Tournee],
    debut: int,
    fin: int,
    vacation: int,
    pause_dur: int,
) -> Tuple[List[Tournee], List[Tournee]]:
    """
    Sélectionne les tournées qui tiennent dans un quart.

    Utilise le temps effectif absolu (incluant attentes inter-tournées) pour
    éviter les dépassements. Une tournée tient si son heure_fin absolue +
    fin_de_poste + pause ≤ heure_fin du quart.

    Returns:
        (tournees_dans_le_quart, tournees_restantes)
    """
    panier: List[Tournee] = []
    heure_eff = debut + config.PRISE_DE_POSTE_MIN  # après prise de poste

    for t in tournees:
        # Début effectif = max(heure_courante, heure_dispo du flux)
        start_eff = max(heure_eff, t.heure_debut)
        dur = t.heure_fin - t.heure_debut
        end_eff = max(start_eff + dur, t.heure_fin)

        # Vérification : la fin effective + pause + fin_poste doit tenir dans le quart
        if end_eff + pause_dur + config.FIN_DE_POSTE_MIN <= fin:
            panier.append(t)
            heure_eff = end_eff
        else:
            break  # consécutif : on s'arrête dès que ça ne rentre plus

    remaining = tournees[len(panier):]
    return panier, remaining


def _erreur_amplitude(vtype: str, num: int, fin_reel: int, end_max: int) -> Dict[str, Any]:
    return {
        "type": "AMPLITUDE_DEPASSEE",
        "statut": "ERREUR",
        "detail": (
            f"{vtype} quart #{num} : fin {minutes_to_hhmm(fin_reel)} > "
            f"limite {minutes_to_hhmm(end_max)}"
        ),
        "concerne": vtype,
        "gravite": "CRITIQUE",
        "action": "Ajouter des véhicules ou élargir la plage horaire.",
    }


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
    Construit un poste chauffeur avec séquence complète d'opérations.

    Gère :
    - Prise de poste
    - Désinfection inter-tournées (transition Sale → Propre)
    - Pause dans la fenêtre ±1h autour du milieu du poste
    - Temps inoccupé
    - Fin de poste
    """
    steps: List[StepOperation] = []
    heure = debut

    temps_conduite = 0
    temps_manutention = 0
    temps_quai_total = 0
    temps_desinfection = 0
    temps_attente = 0
    temps_inoccupe = 0
    nb_desinfections = 0

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
    pause_ws = milieu - config.PAUSE_WINDOW_HOURS
    pause_we = milieu + config.PAUSE_WINDOW_HOURS
    pause_inseree = False

    # Suivi de l'état sanitaire du véhicule entre tournées
    etat_veh = config.SANITAIRE_PROPRE

    for tournee in tournees:
        if not tournee.steps:
            continue

        # ── Désinfection inter-tournées ──────────────────────────────────
        # Nécessaire si le véhicule est Sale et que la prochaine tournée
        # implique du Propre (route_builder repart toujours de PROPRE)
        if etat_veh == config.SANITAIRE_SALE:
            has_propre = any(
                s.type_operation == config.OP_CHARGEMENT
                and s.statut_sanitaire == config.SANITAIRE_PROPRE
                for s in tournee.steps
            )
            if has_propre:
                # Vérifier que le véhicule est bien au stationnement initial
                # (route_builder y retourne à la fin de chaque tournée)
                steps.append(StepOperation(
                    heure_debut=heure,
                    heure_fin=heure + config.DESINFECTION_DURATION,
                    type_operation=config.OP_DESINFECTION,
                    site=veh.stationnement_initial,
                    statut_sanitaire=config.SANITAIRE_PROPRE,
                    commentaire="Désinfection inter-tournées (Sale → Propre)",
                ))
                heure += config.DESINFECTION_DURATION
                etat_veh = config.SANITAIRE_PROPRE
                temps_desinfection += config.DESINFECTION_DURATION
                nb_desinfections += 1

        # ── Pause (si fenêtre atteinte et stationnement initial) ─────────
        if (not pause_inseree
                and pause_ws <= heure <= pause_we
                and tournee.steps[0].site == veh.stationnement_initial):
            steps.append(StepOperation(
                heure_debut=heure,
                heure_fin=heure + pause_dur,
                type_operation=config.OP_PAUSE,
                site=veh.stationnement_initial,
            ))
            heure += pause_dur
            pause_inseree = True

        # ── Étapes de la tournée ─────────────────────────────────────────
        for step in tournee.steps:
            dur = step.heure_fin - step.heure_debut
            if dur <= 0:
                continue

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
                nb_desinfections += 1
            elif step.type_operation == config.OP_ATTENTE:
                temps_attente += dur

        # Mettre à jour l'état sanitaire à partir de la dernière étape
        etat_veh = tournee.steps[-1].statut_sanitaire

    # ── Pause hors fenêtre si non encore insérée ─────────────────────────
    if not pause_inseree:
        steps.append(StepOperation(
            heure_debut=heure,
            heure_fin=heure + pause_dur,
            type_operation=config.OP_PAUSE,
            site=veh.stationnement_initial,
        ))
        heure += pause_dur

    # ── Temps inoccupé ────────────────────────────────────────────────────
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
    elif heure > fin_travail:
        # Dépassement : le fin_poste est repoussé à heure réelle
        # (ne devrait plus arriver grâce au _remplir_quart corrigé)
        logger.warning(
            "Poste %d (%s) dépasse de %d min — dernier step à %s, fin prévue %s",
            poste_id, vtype, heure - fin_travail,
            minutes_to_hhmm(heure), minutes_to_hhmm(fin)
        )
        fin = heure + config.FIN_DE_POSTE_MIN
        vacation = fin - debut

    # ── Fin de poste ──────────────────────────────────────────────────────
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
        nb_desinfections=nb_desinfections,
    )
