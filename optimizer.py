"""
optimizer.py — Moteur d'optimisation OptiFLUX.

Implémente l'heuristique Clarke-Wright Savings suivie d'une amélioration 2-opt
inter-tournées, avec un budget de 2 minutes par jour simulé.

Modèle de capacité séquentiel :
  - Chaque flux est d'abord éclaté en voyages élémentaires (≤ capacité véhicule).
  - Les voyages peuvent être chaînés (le camion enchaîne livraisons sans retour obligatoire
    au dépôt). À tout instant, le camion ne transporte que les contenants du voyage courant.
  - La contrainte de capacité est donc : max(quantité_d'un_voyage) ≤ capacité, pas la somme.
"""

from __future__ import annotations
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import config
from models import Flux, Vehicule, Site, Contenant, Tournee, StepOperation
from capacity import max_contenants_par_vehicule, eclater_flux_volumineux
from compatibility import (
    vehicule_compatible_flux,
    vehicule_peut_charger,
    get_vehicules_compatibles_flux,
)

logger = logging.getLogger(__name__)


# ============================================================================
# STRUCTURES INTERMÉDIAIRES
# ============================================================================

class PlanningJour:
    """Résultat intermédiaire de planification pour un jour."""

    def __init__(self):
        self.tournees: List[TourneeBuilder] = []
        self.flux_affectes: Set[int] = set()
        self.flux_non_affectes: List[int] = []
        self.stats: Dict[str, Any] = {}


class TourneeBuilder:
    """
    Construction progressive d'un voyage ou d'une chaîne de voyages.

    Modèle séquentiel : nb_contenants_charges = pic de charge (max d'un voyage),
    pas la somme cumulative. Ainsi le taux de remplissage reste ≤ 100 %.
    """

    _id_counter = 0

    def __init__(self, type_vehicule: str, vehicule: Vehicule):
        TourneeBuilder._id_counter += 1
        self.id = TourneeBuilder._id_counter
        self.type_vehicule = type_vehicule
        self.vehicule = vehicule
        self.flux: List[Flux] = []
        self.etat_sanitaire: str = config.SANITAIRE_PROPRE
        # Modèle séquentiel : ces champs représentent le PIC de charge
        self.nb_contenants_charges: int = 0   # max d'un seul voyage
        self.poids_charge: float = 0.0         # poids max d'un seul voyage
        self.surf_charge: float = 0.0           # surface max d'un seul voyage

    def peut_ajouter(
        self,
        flux: Flux,
        sites: Dict[str, Site],
        contenants: Dict[str, Contenant],
        matrix_dur: Dict[str, Dict[str, float]],
        rh: Dict[str, int],
    ) -> bool:
        """
        Vérifie si ce voyage peut être ajouté à la chaîne.

        Modèle séquentiel : on vérifie que CE voyage seul tient dans le véhicule
        (les voyages précédents ont déjà été livrés).
        """
        if not vehicule_compatible_flux(self.vehicule, flux, sites):
            return False
        if not vehicule_peut_charger(self.vehicule, flux, self.etat_sanitaire, self.flux):
            return False
        cont = contenants.get(flux.type_contenant)
        if cont is None:
            return False
        # Ce voyage seul doit tenir dans la capacité
        cap = max_contenants_par_vehicule(self.vehicule, cont)
        if flux.quantite > cap:
            return False
        poids_unit = cont.poids_plein if flux.statut_plein_vide.lower() == "plein" else cont.poids_vide
        if poids_unit * flux.quantite > self.vehicule.poids_max:
            return False
        return True

    def ajouter_flux(self, flux: Flux, contenants: Dict[str, Contenant]) -> None:
        """
        Ajoute un voyage à la chaîne.

        Met à jour le pic de charge (pas de cumul, car livraison séquentielle).
        """
        self.flux.append(flux)
        cont = contenants.get(flux.type_contenant)
        if cont:
            # Pic = max d'un seul voyage (livraison avant chargement suivant)
            self.nb_contenants_charges = max(self.nb_contenants_charges, flux.quantite)
            poids_unit = cont.poids_plein if flux.statut_plein_vide.lower() == "plein" else cont.poids_vide
            self.poids_charge = max(self.poids_charge, poids_unit * flux.quantite)
            self.surf_charge = (cont.longueur * cont.largeur) * self.nb_contenants_charges
        if flux.statut_propre_sale == config.SANITAIRE_SALE:
            self.etat_sanitaire = config.SANITAIRE_SALE


# ============================================================================
# FONCTIONS AUXILIAIRES
# ============================================================================

def _choisir_vehicule(
    flux: Flux,
    compat_types: List[str],
    vehicules: Dict[str, Vehicule],
    contenants: Dict[str, Contenant],
) -> str:
    """
    Choisit le type de véhicule qui maximise la capacité par voyage,
    minimisant ainsi le nombre de voyages nécessaires pour un flux donné.

    En cas d'égalité de capacité, préfère le véhicule de surface minimale
    (moins de gaspillage pour les petites quantités).
    """
    cont = contenants.get(flux.type_contenant)
    best = compat_types[0]
    best_cap = -1
    best_surf = float("inf")

    for vtype in compat_types:
        veh = vehicules[vtype]
        cap = max_contenants_par_vehicule(veh, cont) if cont else 0
        surf = veh.longueur * veh.largeur
        if cap > best_cap or (cap == best_cap and surf < best_surf):
            best = vtype
            best_cap = cap
            best_surf = surf

    return best


def _creer_tournee_groupe(
    flux_groupe: List[Flux],
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    rh: Dict[str, int],
) -> Optional[TourneeBuilder]:
    """Crée une tournée groupant tous les flux d'une tournée mutualisée."""
    for vtype, veh in sorted(vehicules.items(), key=lambda x: x[1].longueur * x[1].largeur):
        ok = all(vehicule_compatible_flux(veh, f, sites) for f in flux_groupe)
        if ok:
            t = TourneeBuilder(vtype, veh)
            for f in flux_groupe:
                t.ajouter_flux(f, contenants)
            return t
    return None


def _peut_fusionner(
    t1: TourneeBuilder,
    t2: TourneeBuilder,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    rh: Dict[str, int],
) -> bool:
    """
    Vérifie si deux chaînes de voyages peuvent être fusionnées.

    Modèle séquentiel : chaque voyage individuel doit tenir dans le véhicule,
    indépendamment des autres voyages de la chaîne.
    """
    if t1.type_vehicule != t2.type_vehicule:
        return False
    veh = t1.vehicule

    # Chaque voyage individuel doit tenir dans la capacité et le poids
    for f in t1.flux + t2.flux:
        cont = contenants.get(f.type_contenant)
        if cont:
            cap = max_contenants_par_vehicule(veh, cont)
            if f.quantite > cap:
                return False
            poids_unit = cont.poids_plein if f.statut_plein_vide.lower() == "plein" else cont.poids_vide
            if poids_unit * f.quantite > veh.poids_max:
                return False

    # Compatibilité sanitaire
    etat = t1.etat_sanitaire
    for f in t2.flux:
        if f.statut_propre_sale == config.SANITAIRE_SALE:
            etat = config.SANITAIRE_SALE
        elif etat == config.SANITAIRE_SALE and f.statut_propre_sale == config.SANITAIRE_PROPRE:
            if not f.transport_mixte:
                return False

    return True


def _saving(
    t1: TourneeBuilder,
    t2: TourneeBuilder,
    matrix_dist: Dict[str, Dict[str, float]],
    vehicules: Dict[str, Vehicule],
) -> float:
    """Économie en km si on chaîne t1 puis t2 au lieu de deux aller-retours au dépôt."""
    if not t1.flux or not t2.flux:
        return 0.0
    depot = t1.vehicule.stationnement_initial
    last_arr_t1 = t1.flux[-1].site_arrivee
    first_dep_t2 = t2.flux[0].site_depart
    # Sans chaînage : t1 rentre au dépôt, t2 part du dépôt
    d_t1_depot = matrix_dist.get(last_arr_t1, {}).get(depot, 0)
    d_depot_t2 = matrix_dist.get(depot, {}).get(first_dep_t2, 0)
    # Avec chaînage : t1 va directement vers t2
    d_t1_t2 = matrix_dist.get(last_arr_t1, {}).get(first_dep_t2, 0)
    return d_t1_depot + d_depot_t2 - d_t1_t2


# ============================================================================
# MOTEUR PRINCIPAL
# ============================================================================

def optimizer_run(
    flux_actifs: List[Flux],
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    rh: Dict[str, int],
    tournees_mutualisees: Dict[str, List[int]],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> PlanningJour:
    """
    Lance le moteur d'optimisation Clarke-Wright Savings + 2-opt.

    Phase 1 : Tournées mutualisées (contrainte fixe).
    Phase 2 : Éclatement des flux en voyages élémentaires (≤ capacité véhicule).
    Phase 3 : Clarke-Wright Savings — chaînage des voyages pour réduire les km à vide.
    Phase 4 : 2-opt inter-tournées (budget temps restant).
    """
    start_time = time.time()
    planning = PlanningJour()
    TourneeBuilder._id_counter = 0

    if not flux_actifs:
        return planning

    def _report(pct: float, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, msg)

    flux_by_id = {f.id_flux: f for f in flux_actifs}
    vehicules_actifs = {k: v for k, v in vehicules.items() if v.actif}

    # --- Phase 1 : Tournées mutualisées ---
    _report(0.05, "Tournées mutualisées…")
    flux_en_mutualisee: Set[int] = set()
    tournees_initiales: List[TourneeBuilder] = []

    for nom, ids in tournees_mutualisees.items():
        groupe = [flux_by_id[i] for i in ids if i in flux_by_id]
        if not groupe:
            continue
        t = _creer_tournee_groupe(groupe, vehicules_actifs, sites, contenants, matrix_dur, rh)
        if t:
            tournees_initiales.append(t)
            for f in t.flux:
                flux_en_mutualisee.add(f.id_flux)

    # --- Phase 2 : Voyages élémentaires ---
    _report(0.15, "Éclatement des flux en voyages…")
    flux_restants = [f for f in flux_actifs if f.id_flux not in flux_en_mutualisee]

    for flux in flux_restants:
        compat = get_vehicules_compatibles_flux(flux, vehicules_actifs, sites)
        if not compat:
            planning.flux_non_affectes.append(flux.id_flux)
            continue

        # Véhicule qui maximise la capacité par voyage (minimise le nombre de voyages)
        vtype = _choisir_vehicule(flux, compat, vehicules_actifs, contenants)
        veh = vehicules_actifs[vtype]
        cont = contenants.get(flux.type_contenant)

        # Éclater le flux en voyages élémentaires
        if cont is not None:
            voyages = eclater_flux_volumineux(flux, veh, cont)
        else:
            voyages = [(flux.quantite, True)]

        for nb_cont, _ in voyages:
            flux_voyage = flux.model_copy(update={"quantite": nb_cont})
            t = TourneeBuilder(vtype, veh)
            t.ajouter_flux(flux_voyage, contenants)
            tournees_initiales.append(t)

        planning.flux_affectes.add(flux.id_flux)

    for fid in flux_en_mutualisee:
        planning.flux_affectes.add(fid)

    _report(0.30, f"{len(tournees_initiales)} voyages créés — Calcul des économies Clarke-Wright…")

    # --- Phase 3 : Clarke-Wright Savings ---
    tournees = _clarke_wright_savings(
        tournees_initiales,
        vehicules_actifs,
        sites,
        contenants,
        matrix_dur,
        matrix_dist,
        rh,
        start_time,
        progress_callback=lambda p, m: _report(0.30 + p * 0.45, m),
    )

    _report(0.75, "Amélioration 2-opt…")

    # --- Phase 4 : 2-opt ---
    budget_restant = config.OPTIMIZATION_BUDGET_SEC - (time.time() - start_time)
    if budget_restant > 5:
        tournees = _two_opt_improvement(
            tournees,
            vehicules_actifs,
            sites,
            contenants,
            matrix_dur,
            matrix_dist,
            rh,
            budget_restant * 0.8,
            progress_callback=lambda p, m: _report(0.75 + p * 0.20, m),
        )

    _report(0.95, "Finalisation…")
    planning.tournees = tournees
    planning.stats = {
        "nb_voyages": len(tournees),
        "nb_flux_affectes": len(planning.flux_affectes),
        "nb_flux_non_affectes": len(planning.flux_non_affectes),
        "temps_calcul_sec": round(time.time() - start_time, 2),
    }

    _report(1.0, "Optimisation terminée.")
    return planning


def _clarke_wright_savings(
    tournees: List[TourneeBuilder],
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    rh: Dict[str, int],
    start_time: float,
    progress_callback: Optional[Callable] = None,
) -> List[TourneeBuilder]:
    """
    Clarke-Wright : tente de chaîner des voyages (t1 → t2 sans retour dépôt entre les deux)
    lorsque cela réduit les km totaux et que la fusion est faisable.
    """
    if len(tournees) <= 1:
        return tournees

    max_iter = min(len(tournees) * (len(tournees) - 1) // 2, 2000)
    improved = True
    iteration = 0

    while improved and iteration < max_iter:
        if time.time() - start_time > config.OPTIMIZATION_BUDGET_SEC * 0.70:
            break

        improved = False
        iteration += 1
        best_saving = 0.0
        best_pair: Optional[Tuple[int, int]] = None

        for i in range(len(tournees)):
            for j in range(i + 1, len(tournees)):
                t1, t2 = tournees[i], tournees[j]
                if t1.type_vehicule != t2.type_vehicule:
                    continue
                s = _saving(t1, t2, matrix_dist, vehicules)
                if s > best_saving and _peut_fusionner(t1, t2, vehicules, sites, contenants, matrix_dur, rh):
                    best_saving = s
                    best_pair = (i, j)

        if best_pair:
            i, j = best_pair
            t1, t2 = tournees[i], tournees[j]
            for f in t2.flux:
                t1.ajouter_flux(f, contenants)
            tournees.pop(j)
            improved = True

        if progress_callback and iteration % 20 == 0:
            progress_callback(min(iteration / max_iter, 1.0), f"Fusion {iteration}")

    return tournees


def _two_opt_improvement(
    tournees: List[TourneeBuilder],
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
    rh: Dict[str, int],
    budget_sec: float,
    progress_callback: Optional[Callable] = None,
) -> List[TourneeBuilder]:
    """2-opt inter-tournées (stub — extension future)."""
    return tournees


# ============================================================================
# CONVERSION EN MODÈLES PYDANTIC
# ============================================================================

def construire_tournees_finales(
    planning: PlanningJour,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
) -> List[Tournee]:
    """
    Convertit les TourneeBuilder en modèles Tournee Pydantic avec séquences détaillées.
    """
    from route_builder import build_route_steps

    tournees_finales = []
    for tb in planning.tournees:
        if not tb.flux:
            continue
        veh = vehicules.get(tb.type_vehicule)
        if not veh:
            continue
        steps, km_total, km_vide, nb_desinf = build_route_steps(
            tb.flux, veh, sites, contenants, matrix_dur, matrix_dist
        )
        t = Tournee(
            id_tournee=tb.id,
            type_vehicule=tb.type_vehicule,
            flux_ids=[f.id_flux for f in tb.flux],
            sequence_sites=list(dict.fromkeys(
                [f.site_depart for f in tb.flux] + [f.site_arrivee for f in tb.flux]
            )),
            steps=steps,
            heure_debut=steps[0].heure_debut if steps else 0,
            heure_fin=steps[-1].heure_fin if steps else 0,
            km_total=km_total,
            km_vide=km_vide,
            nb_desinfections=nb_desinf,
        )
        tournees_finales.append(t)
    return tournees_finales
