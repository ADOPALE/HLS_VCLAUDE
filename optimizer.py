"""
optimizer.py — Moteur d'optimisation OptiFLUX (VRPPDTW).

Vehicle Routing Problem with Pickup & Delivery and Time Windows.

Un véhicule parcourt un circuit multi-stops. À chaque site, il peut :
  - charger un ou plusieurs flux (pickup)
  - décharger un ou plusieurs flux (delivery)
  - faire les deux simultanément

Contraintes :
  - Capacité : le PIC de charge à tout instant ≤ capacité du véhicule
  - Fenêtres horaires : la livraison arrive avant heure_max de chaque flux
  - Sanitaire : les flux propres et sales sont compatibles selon les règles (mixité)
    → on minimise le nombre de désinfections nécessaires

Algorithme :
  Phase 1  Pré-affectation sanitaire — routes propres, routes sales, mixtes.
  Phase 2  Construction — heuristique d'insertion la moins chère pour chaque flux.
  Phase 3  Amélioration — OR-opt (relocalisation) + 2-opt avec budget temps.
"""
from __future__ import annotations

import copy
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import config
from models import Flux, Vehicule, Site, Contenant, Tournee
from capacity import max_contenants_par_vehicule
from compatibility import vehicule_compatible_flux, vehicule_peut_charger
from time_windows import calcul_t_min

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# STRUCTURES DE DONNÉES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class VisiteSite:
    """Un arrêt du véhicule dans un circuit."""
    site: str
    flux_charges: List[Flux] = field(default_factory=list)
    flux_decharges: List[Flux] = field(default_factory=list)

    @property
    def heure_min(self) -> int:
        """Heure la plus tôt à laquelle la visite peut commencer."""
        if self.flux_charges:
            return min(f.heure_dispo for f in self.flux_charges)
        return 0

    @property
    def heure_max(self) -> int:
        """Heure la plus tardive à laquelle on doit avoir quitté ce site."""
        candidates = []
        if self.flux_charges:
            candidates += [f.heure_max_livraison for f in self.flux_charges]
        if self.flux_decharges:
            candidates += [f.heure_max_livraison for f in self.flux_decharges]
        return min(candidates) if candidates else 1440


class RoutePDTW:
    """
    Circuit multi-stops pour un type de véhicule.

    Un circuit est une séquence de VisiteSite ordonnée.
    Le véhicule part du stationnement initial, visite chaque site,
    et revient à son point de départ.
    """
    _id_counter = 0

    def __init__(self, vehicule: Vehicule):
        RoutePDTW._id_counter += 1
        self.id = RoutePDTW._id_counter
        self.vehicule = vehicule
        self.visites: List[VisiteSite] = []
        self.flux_ids: Set[int] = set()

    # ── Accès ────────────────────────────────────────────────────────────

    def tous_flux(self) -> List[Flux]:
        seen, result = set(), []
        for v in self.visites:
            for f in v.flux_charges:
                if f.id_flux not in seen:
                    seen.add(f.id_flux)
                    result.append(f)
        return result

    def sites_circuit(self) -> List[str]:
        depot = self.vehicule.stationnement_initial
        return [depot] + [v.site for v in self.visites] + [depot]

    # ── Métriques ────────────────────────────────────────────────────────

    def cout_km(self, matrix_dist: Dict) -> float:
        sites = self.sites_circuit()
        return sum(
            matrix_dist.get(sites[i], {}).get(sites[i + 1], 0.0)
            for i in range(len(sites) - 1)
        )

    def pic_charge(self, contenants: Dict[str, Contenant]) -> Dict[str, int]:
        """Pic de charge par type de contenant sur l'ensemble du circuit."""
        charge: Dict[str, int] = {}
        pic: Dict[str, int] = {}
        for v in self.visites:
            for f in v.flux_decharges:
                charge[f.type_contenant] = charge.get(f.type_contenant, 0) - f.quantite
            for f in v.flux_charges:
                charge[f.type_contenant] = charge.get(f.type_contenant, 0) + f.quantite
                pic[f.type_contenant] = max(
                    pic.get(f.type_contenant, 0),
                    charge.get(f.type_contenant, 0),
                )
        return pic

    def respecte_capacite(self, contenants: Dict[str, Contenant]) -> bool:
        pics = self.pic_charge(contenants)
        for cont_type, qty in pics.items():
            cont = contenants.get(cont_type)
            if cont is None:
                continue
            cap = max_contenants_par_vehicule(self.vehicule, cont)
            if qty > cap:
                return False
        return True

    def nb_desinfections(self) -> int:
        """Nombre de désinfections nécessaires sur ce circuit."""
        etat = config.SANITAIRE_PROPRE
        count = 0
        for v in self.visites:
            # Décharger d'abord (réduit la charge), puis charger
            for f in v.flux_decharges:
                pass  # l'état sanitaire ne change pas au déchargement
            for f in v.flux_charges:
                if (f.statut_propre_sale == config.SANITAIRE_PROPRE
                        and etat == config.SANITAIRE_SALE):
                    count += 1
                    etat = config.SANITAIRE_PROPRE
                if f.statut_propre_sale == config.SANITAIRE_SALE:
                    etat = config.SANITAIRE_SALE
        return count

    def etat_sanitaire_final(self) -> str:
        etat = config.SANITAIRE_PROPRE
        for v in self.visites:
            for f in v.flux_charges:
                if f.statut_propre_sale == config.SANITAIRE_SALE:
                    etat = config.SANITAIRE_SALE
        return etat

    # ── Faisabilité temporelle ────────────────────────────────────────────

    def respecte_temps(
        self,
        sites: Dict[str, Site],
        matrix_dur: Dict,
    ) -> bool:
        """
        Vérifie que les fenêtres temporelles de tous les flux sont respectées.
        Calcule l'heure d'arrivée effective à chaque site et vérifie la contrainte
        heure_max_livraison pour chaque flux déchargé.
        """
        depot = self.vehicule.stationnement_initial
        heure = config.DEFAULT_RH["start_min"]
        pos = depot

        for v in self.visites:
            trajet = matrix_dur.get(pos, {}).get(v.site, 0)
            heure += trajet

            # Temps de mise à quai
            site_obj = sites.get(v.site)
            if site_obj and site_obj.presence_quai and (v.flux_charges or v.flux_decharges):
                heure += self.vehicule.temps_mise_quai

            # Attente si flux pas encore disponibles
            if v.flux_charges:
                heure_min_dispo = min(f.heure_dispo for f in v.flux_charges)
                heure = max(heure, heure_min_dispo)

            # Manutention de déchargement
            for f in v.flux_decharges:
                manu = (self.vehicule.manu_avec_quai if (site_obj and site_obj.presence_quai)
                        else (self.vehicule.manu_sans_quai or 0.0))
                heure += math.ceil(manu * f.quantite)
                # Vérification fenêtre
                if heure > f.heure_max_livraison:
                    return False

            # Manutention de chargement
            for f in v.flux_charges:
                manu = (self.vehicule.manu_avec_quai if (site_obj and site_obj.presence_quai)
                        else (self.vehicule.manu_sans_quai or 0.0))
                heure += math.ceil(manu * f.quantite)

            pos = v.site

        return True

    # ── Clone ─────────────────────────────────────────────────────────────

    def clone(self) -> "RoutePDTW":
        r = RoutePDTW(self.vehicule)
        r.id = self.id
        r.flux_ids = set(self.flux_ids)
        r.visites = [
            VisiteSite(
                site=v.site,
                flux_charges=list(v.flux_charges),
                flux_decharges=list(v.flux_decharges),
            )
            for v in self.visites
        ]
        return r

    # ── Insertion d'un flux ───────────────────────────────────────────────

    def _index_site(self, site: str) -> Optional[int]:
        for i, v in enumerate(self.visites):
            if v.site == site:
                return i
        return None

    def inserer_flux(
        self,
        flux: Flux,
        sites: Dict[str, Site],
        contenants: Dict[str, Contenant],
        matrix_dur: Dict,
        matrix_dist: Dict,
    ) -> bool:
        """
        Tente d'insérer un flux dans le circuit de façon optimale.

        Stratégie :
        1. Si le site de départ existe déjà dans le circuit, ajouter le chargement
           à cet arrêt existant (évite un aller-retour inutile).
        2. Sinon, essayer toutes les positions d'insertion du chargement.
        3. Pour le déchargement, même logique.
        4. Choisir la combinaison (pos_charge, pos_decharge) qui minimise le km
           total tout en respectant capacité, temps et sanitaire.

        Returns True si une insertion faisable a été trouvée.
        """
        n = len(self.visites)
        best_cout = float("inf")
        best_config: Optional[Tuple] = None  # (i_charge, i_decharge, new_site_dep, new_site_arr)

        # Positions pour le chargement : sites existants (si même site) ou nouvelles insertions
        charge_positions = []
        idx_dep = self._index_site(flux.site_depart)
        if idx_dep is not None:
            charge_positions.append(("existing", idx_dep))
        for i in range(n + 1):
            charge_positions.append(("new", i))

        for charge_type, i_charge_raw in charge_positions:
            # Positions pour le déchargement
            decharge_positions = []
            idx_arr = self._index_site(flux.site_arrivee)
            if idx_arr is not None and idx_arr >= (i_charge_raw if charge_type == "existing" else i_charge_raw):
                decharge_positions.append(("existing", idx_arr))
            for j in range((i_charge_raw if charge_type == "existing" else i_charge_raw), n + 2):
                decharge_positions.append(("new", j))

            for decharge_type, i_decharge_raw in decharge_positions:
                # Construire le circuit test
                test = self.clone()
                test._appliquer_insertion(flux, charge_type, i_charge_raw,
                                          decharge_type, i_decharge_raw)
                test.flux_ids.add(flux.id_flux)

                # Vérifications
                if not test.respecte_capacite(contenants):
                    continue
                if not test.respecte_temps(sites, matrix_dur):
                    continue

                cout = test.cout_km(matrix_dist)
                # Pénalité désinfection (coût équivalent à 50 km)
                cout += test.nb_desinfections() * 50

                if cout < best_cout:
                    best_cout = cout
                    best_config = (charge_type, i_charge_raw, decharge_type, i_decharge_raw)

        if best_config:
            ct, ic, dt, id_ = best_config
            self._appliquer_insertion(flux, ct, ic, dt, id_)
            self.flux_ids.add(flux.id_flux)
            return True
        return False

    def _appliquer_insertion(
        self,
        flux: Flux,
        charge_type: str, i_charge: int,
        decharge_type: str, i_decharge: int,
    ) -> None:
        """Applique l'insertion dans le circuit."""
        if charge_type == "existing":
            self.visites[i_charge].flux_charges.append(flux)
        else:
            self.visites.insert(i_charge, VisiteSite(
                site=flux.site_depart,
                flux_charges=[flux],
            ))
            # Ajuster i_decharge si on a décalé
            if decharge_type == "new" and i_decharge > i_charge:
                i_decharge += 1

        if decharge_type == "existing":
            self.visites[i_decharge].flux_decharges.append(flux)
        else:
            self.visites.insert(i_decharge, VisiteSite(
                site=flux.site_arrivee,
                flux_decharges=[flux],
            ))

        # Nettoyer les visites vides
        self.visites = [v for v in self.visites
                        if v.flux_charges or v.flux_decharges]

    # ── Retrait d'un flux ─────────────────────────────────────────────────

    def retirer_flux(self, flux_id: int) -> Optional[Flux]:
        """Retire un flux du circuit. Retourne le flux retiré ou None."""
        removed = None
        for v in self.visites:
            for f in list(v.flux_charges):
                if f.id_flux == flux_id:
                    v.flux_charges.remove(f)
                    removed = f
            for f in list(v.flux_decharges):
                if f.id_flux == flux_id:
                    v.flux_decharges.remove(f)
        self.visites = [v for v in self.visites
                        if v.flux_charges or v.flux_decharges]
        if removed:
            self.flux_ids.discard(flux_id)
        return removed


# ════════════════════════════════════════════════════════════════════════════
# RÉSULTAT DE PLANIFICATION
# ════════════════════════════════════════════════════════════════════════════

class PlanningJour:
    def __init__(self):
        self.routes: List[RoutePDTW] = []
        self.flux_affectes: Set[int] = set()
        self.flux_non_affectes: List[int] = []
        self.stats: Dict[str, Any] = {}

    # Alias pour compatibilité avec le reste du code
    @property
    def tournees(self):
        return self.routes

    @property
    def flux_non_affectes_set(self) -> Set[int]:
        return set(self.flux_non_affectes)


# ════════════════════════════════════════════════════════════════════════════
# FONCTIONS UTILITAIRES
# ════════════════════════════════════════════════════════════════════════════

def _flux_est_propre(flux: Flux) -> bool:
    return flux.statut_propre_sale == config.SANITAIRE_PROPRE

def _flux_est_sale(flux: Flux) -> bool:
    return flux.statut_propre_sale == config.SANITAIRE_SALE

def _choisir_vehicule_max_cap(
    flux: Flux,
    compat_types: List[str],
    vehicules: Dict[str, Vehicule],
    contenants: Dict[str, Contenant],
) -> str:
    """Choisit le type de véhicule avec la plus grande capacité pour ce flux."""
    cont = contenants.get(flux.type_contenant)
    best, best_cap = compat_types[0], -1
    for vtype in compat_types:
        veh = vehicules[vtype]
        cap = max_contenants_par_vehicule(veh, cont) if cont else int(veh.longueur * veh.largeur)
        if cap > best_cap:
            best, best_cap = vtype, cap
    return best

def _get_compat_types(
    flux: Flux,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
) -> List[str]:
    return [
        vtype for vtype, veh in vehicules.items()
        if veh.actif and vehicule_compatible_flux(veh, flux, sites)
    ]


# ════════════════════════════════════════════════════════════════════════════
# MOTEUR PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

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
    Moteur VRPPDTW OptiFLUX.

    Phase 1 : Tournées mutualisées (contrainte fixe).
    Phase 2 : Pré-affectation sanitaire (routes propres / sales en priorité).
    Phase 3 : Construction — heuristique d'insertion la moins chère.
    Phase 4 : Amélioration — OR-opt relocalisation + 2-opt inter-routes.
    """
    t0 = time.time()
    planning = PlanningJour()
    RoutePDTW._id_counter = 0

    if not flux_actifs:
        return planning

    def _cb(pct: float, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, msg)
        logger.debug("[%.0f%%] %s", pct * 100, msg)

    vehicules_actifs = {k: v for k, v in vehicules.items() if v.actif}
    flux_by_id = {f.id_flux: f for f in flux_actifs}

    # ── Phase 1 : Tournées mutualisées ────────────────────────────────────
    _cb(0.02, "Tournées mutualisées…")
    flux_mutualisees: Set[int] = set()
    routes: List[RoutePDTW] = []

    for nom, ids in tournees_mutualisees.items():
        groupe = [flux_by_id[i] for i in ids if i in flux_by_id]
        if not groupe:
            continue
        vtype = _choisir_vehicule_max_cap(
            groupe[0],
            _get_compat_types(groupe[0], vehicules_actifs, sites),
            vehicules_actifs, contenants,
        )
        route = RoutePDTW(vehicules_actifs[vtype])
        for f in groupe:
            route.inserer_flux(f, sites, contenants, matrix_dur, matrix_dist)
            flux_mutualisees.add(f.id_flux)
        routes.append(route)
        planning.flux_affectes.update(flux_mutualisees)

    # ── Phase 2+3 : Construction ──────────────────────────────────────────
    flux_restants = [f for f in flux_actifs if f.id_flux not in flux_mutualisees]

    # Ordre d'insertion : urgents → fenêtres étroites → fenêtres larges
    flux_restants.sort(key=lambda f: (
        not f.urgent,
        f.heure_max_livraison - f.heure_dispo,  # fenêtres courtes d'abord
        f.heure_dispo,
    ))

    n_flux = len(flux_restants)
    _cb(0.05, f"Construction de {n_flux} flux…")

    for i, flux in enumerate(flux_restants):
        pct = 0.05 + 0.45 * (i / max(n_flux, 1))
        if i % 10 == 0:
            _cb(pct, f"Insertion flux {i+1}/{n_flux}…")

        compat = _get_compat_types(flux, vehicules_actifs, sites)
        if not compat:
            planning.flux_non_affectes.append(flux.id_flux)
            continue

        # Éclater si quantité > capacité max
        vtype_cap = _choisir_vehicule_max_cap(flux, compat, vehicules_actifs, contenants)
        veh_cap = vehicules_actifs[vtype_cap]
        cont = contenants.get(flux.type_contenant)
        cap = max_contenants_par_vehicule(veh_cap, cont) if cont else flux.quantite

        if flux.quantite > cap and cap > 0:
            flux_parts = _eclater(flux, cap)
        else:
            flux_parts = [flux]

        for part in flux_parts:
            insere = False

            # 1. Essayer d'insérer dans une route existante compatible
            # Priorité : routes de même statut sanitaire (évite désinfection)
            same_statut = [r for r in routes
                           if vehicule_compatible_flux(r.vehicule, part, sites)
                           and _sanitaire_compatible(r, part)]
            any_route = [r for r in routes
                         if vehicule_compatible_flux(r.vehicule, part, sites)
                         and r not in same_statut]

            for route_list in (same_statut, any_route):
                # Trier par coût d'insertion croissant (heuristique: closest depot)
                route_list.sort(key=lambda r: r.cout_km(matrix_dist))
                for r in route_list:
                    if r.inserer_flux(part, sites, contenants, matrix_dur, matrix_dist):
                        planning.flux_affectes.add(part.id_flux)
                        insere = True
                        break
                if insere:
                    break

            # 2. Nouvelle route
            if not insere:
                vtype = _choisir_vehicule_max_cap(part, compat, vehicules_actifs, contenants)
                r = RoutePDTW(vehicules_actifs[vtype])
                if r.inserer_flux(part, sites, contenants, matrix_dur, matrix_dist):
                    routes.append(r)
                    planning.flux_affectes.add(part.id_flux)
                else:
                    planning.flux_non_affectes.append(part.id_flux)

    planning.routes = routes
    _cb(0.50, f"Construction terminée : {len(routes)} circuits")

    # ── Phase 4 : Amélioration OR-opt + 2-opt ────────────────────────────
    budget = config.OPTIMIZATION_BUDGET_SEC - (time.time() - t0)
    if budget > 2:
        _cb(0.51, "Amélioration OR-opt…")
        routes = _oropt_improvement(
            routes, sites, contenants, matrix_dur, matrix_dist, rh,
            budget * 0.6,
            cb=lambda p, m: _cb(0.51 + p * 0.25, m),
        )

    budget2 = config.OPTIMIZATION_BUDGET_SEC - (time.time() - t0)
    if budget2 > 2:
        _cb(0.76, "Amélioration 2-opt…")
        routes = _twoopt_improvement(
            routes, sites, contenants, matrix_dur, matrix_dist,
            budget2 * 0.9,
            cb=lambda p, m: _cb(0.76 + p * 0.20, m),
        )

    planning.routes = routes
    planning.stats = {
        "nb_circuits": len(routes),
        "nb_flux_affectes": len(planning.flux_affectes),
        "nb_flux_non_affectes": len(planning.flux_non_affectes),
        "temps_calcul_sec": round(time.time() - t0, 1),
    }
    _cb(1.0, "Optimisation terminée.")
    return planning


def _eclater(flux: Flux, cap: int) -> List[Flux]:
    """Éclate un flux en parties de taille ≤ cap."""
    parts = []
    reste = flux.quantite
    while reste > 0:
        qty = min(reste, cap)
        parts.append(flux.model_copy(update={"quantite": qty}))
        reste -= qty
    return parts


def _sanitaire_compatible(route: RoutePDTW, flux: Flux) -> bool:
    """True si insérer ce flux n'augmente pas le nombre de désinfections."""
    etat = route.etat_sanitaire_final()
    if flux.statut_propre_sale == config.SANITAIRE_PROPRE and etat == config.SANITAIRE_SALE:
        return False  # forcerait une désinfection
    return True


def _part_compat(flux: Flux, vehicule: Vehicule, sites: Dict[str, Site]) -> bool:
    return vehicule_compatible_flux(vehicule, flux, sites)





# ════════════════════════════════════════════════════════════════════════════
# AMÉLIORATION OR-OPT (relocalisation de flux entre routes)
# ════════════════════════════════════════════════════════════════════════════

def _oropt_improvement(
    routes: List[RoutePDTW],
    sites: Dict,
    contenants: Dict,
    matrix_dur: Dict,
    matrix_dist: Dict,
    rh: Dict,
    budget_sec: float,
    cb: Optional[Callable] = None,
) -> List[RoutePDTW]:
    """
    OR-opt : essaie de déplacer un flux d'une route vers une autre.
    Si la route source devient vide, la supprime.
    Boucle jusqu'à épuisement du budget.
    """
    t0 = time.time()
    improved = True
    iteration = 0

    while improved and (time.time() - t0) < budget_sec:
        improved = False
        iteration += 1
        if cb and iteration % 5 == 0:
            pct = min((time.time() - t0) / budget_sec, 1.0)
            cb(pct, f"OR-opt itération {iteration}")

        best_gain = 0.0
        best_move: Optional[Tuple] = None  # (route_src_idx, flux_id, route_dst_idx)

        for i, r_src in enumerate(routes):
            for flux_id in list(r_src.flux_ids):
                flux = next((f for v in r_src.visites
                             for f in v.flux_charges if f.id_flux == flux_id), None)
                if flux is None:
                    continue

                cout_src_avant = r_src.cout_km(matrix_dist)

                # Simuler le retrait
                src_test = r_src.clone()
                src_test.retirer_flux(flux_id)
                cout_src_apres = src_test.cout_km(matrix_dist)
                gain_base = cout_src_avant - cout_src_apres

                for j, r_dst in enumerate(routes):
                    if i == j:
                        continue
                    if not vehicule_compatible_flux(r_dst.vehicule, flux, sites):
                        continue

                    cout_dst_avant = r_dst.cout_km(matrix_dist)
                    dst_test = r_dst.clone()
                    if not dst_test.inserer_flux(flux, sites, contenants, matrix_dur, matrix_dist):
                        continue

                    cout_dst_apres = dst_test.cout_km(matrix_dist)
                    gain = gain_base - (cout_dst_apres - cout_dst_avant)
                    # Pénalité désinfection
                    gain -= (dst_test.nb_desinfections() - r_dst.nb_desinfections()) * 50

                    if gain > best_gain:
                        best_gain = gain
                        best_move = (i, flux_id, j)

        if best_move:
            i_src, flux_id, i_dst = best_move
            flux = routes[i_src].retirer_flux(flux_id)
            if flux:
                routes[i_dst].inserer_flux(flux, sites, contenants, matrix_dur, matrix_dist)
            # Supprimer routes vides
            routes = [r for r in routes if r.flux_ids]
            improved = True

    return routes


# ════════════════════════════════════════════════════════════════════════════
# AMÉLIORATION 2-OPT (échange de segments entre routes)
# ════════════════════════════════════════════════════════════════════════════

def _twoopt_improvement(
    routes: List[RoutePDTW],
    sites: Dict,
    contenants: Dict,
    matrix_dur: Dict,
    matrix_dist: Dict,
    budget_sec: float,
    cb: Optional[Callable] = None,
) -> List[RoutePDTW]:
    """
    2-opt inter-routes : échange de séquences de visites entre deux routes
    du même type de véhicule lorsque cela réduit le coût total.
    """
    t0 = time.time()
    improved = True
    iteration = 0

    while improved and (time.time() - t0) < budget_sec:
        improved = False
        iteration += 1
        if cb and iteration % 5 == 0:
            cb(min((time.time() - t0) / budget_sec, 1.0), f"2-opt itération {iteration}")

        for i in range(len(routes)):
            for j in range(i + 1, len(routes)):
                if (time.time() - t0) >= budget_sec:
                    return routes
                r1, r2 = routes[i], routes[j]
                if r1.vehicule.type_vehicule != r2.vehicule.type_vehicule:
                    continue

                cout_avant = r1.cout_km(matrix_dist) + r2.cout_km(matrix_dist)

                # Essayer d'échanger la dernière visite de r1 avec la première de r2
                if not r1.visites or not r2.visites:
                    continue

                r1t, r2t = r1.clone(), r2.clone()
                last_r1 = r1t.visites.pop()
                first_r2 = r2t.visites.pop(0)

                r1t.visites.append(first_r2)
                r2t.visites.insert(0, last_r1)

                if (r1t.respecte_capacite(contenants)
                        and r2t.respecte_capacite(contenants)
                        and r1t.respecte_temps(sites, matrix_dur)
                        and r2t.respecte_temps(sites, matrix_dur)):
                    cout_apres = r1t.cout_km(matrix_dist) + r2t.cout_km(matrix_dist)
                    pen = ((r1t.nb_desinfections() + r2t.nb_desinfections())
                           - (r1.nb_desinfections() + r2.nb_desinfections())) * 50
                    if cout_apres + pen < cout_avant:
                        routes[i] = r1t
                        routes[j] = r2t
                        improved = True

    return routes


# ════════════════════════════════════════════════════════════════════════════
# CONVERSION VERS MODÈLES PYDANTIC (Tournee)
# ════════════════════════════════════════════════════════════════════════════

def construire_tournees_finales(
    planning: PlanningJour,
    vehicules: Dict[str, Vehicule],
    sites: Dict[str, Site],
    contenants: Dict[str, Contenant],
    matrix_dur: Dict[str, Dict[str, float]],
    matrix_dist: Dict[str, Dict[str, float]],
) -> List[Tournee]:
    """
    Convertit les RoutePDTW en modèles Tournee Pydantic avec séquences détaillées.
    """
    from route_builder import build_route_from_visites

    tournees = []
    for route in planning.routes:
        if not route.flux_ids:
            continue
        veh = route.vehicule

        steps, km_total, km_vide, nb_desinf = build_route_from_visites(
            route.visites, veh, sites, contenants, matrix_dur, matrix_dist
        )
        if not steps:
            continue

        t = Tournee(
            id_tournee=route.id,
            type_vehicule=veh.type_vehicule,
            flux_ids=list(route.flux_ids),
            sequence_sites=[v.site for v in route.visites],
            steps=steps,
            heure_debut=steps[0].heure_debut if steps else 0,
            heure_fin=steps[-1].heure_fin if steps else 0,
            km_total=km_total,
            km_vide=km_vide,
            nb_desinfections=nb_desinf,
        )
        tournees.append(t)

    return tournees
