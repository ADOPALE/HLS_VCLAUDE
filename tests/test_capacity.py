"""
test_capacity.py — Tests des calculs de capacité véhicule OptiFLUX.

Couvre : max_contenants_par_vehicule, _grid_capacity, check_poids_ok,
         taux_remplissage_surface, taux_remplissage_poids, eclater_flux_volumineux.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capacity import (
    max_contenants_par_vehicule,
    _grid_capacity,
    check_poids_ok,
    taux_remplissage_surface,
    taux_remplissage_poids,
    eclater_flux_volumineux,
)


# ---------------------------------------------------------------------------
# _grid_capacity — arrangement rectangulaire
# ---------------------------------------------------------------------------

class TestGridCapacity:
    """Tests du calcul de capacité en grille rectangulaire."""

    def test_grille_exacte(self):
        """4 contenants dans un espace de 2×2 cases."""
        assert _grid_capacity(2.0, 2.0, 1.0, 1.0) == 4

    def test_grille_avec_reste(self):
        """Espace 2.5×2.5, contenants 1×1 → 4 (2×2 cases entières)."""
        assert _grid_capacity(2.5, 2.5, 1.0, 1.0) == 4

    def test_contenant_plus_grand_que_vehicule(self):
        """Contenant qui ne rentre pas du tout."""
        assert _grid_capacity(0.5, 0.5, 1.0, 1.0) == 0

    def test_une_seule_dimension_trop_grande(self):
        """Longueur ok mais largeur insuffisante."""
        assert _grid_capacity(3.0, 0.5, 1.0, 1.0) == 0

    def test_dimension_zero_contenant(self):
        """Contenant de dimension 0 → 0."""
        assert _grid_capacity(10.0, 10.0, 0.0, 1.0) == 0

    def test_pl19t_rolls_linge(self):
        """PL19T (7.5×2.4) avec rolls linge (0.8×0.6) → 9 cols × 4 rows = 36."""
        # 7.5 / 0.8 = 9.375 → 9 colonnes ; 2.4 / 0.6 = 4 rangées
        assert _grid_capacity(7.5, 2.4, 0.8, 0.6) == 36


# ---------------------------------------------------------------------------
# max_contenants_par_vehicule — avec rotation
# ---------------------------------------------------------------------------

class TestMaxContenant:
    """Tests du calcul de capacité avec rotation du contenant."""

    def test_pl19t_rolls(self, vehicule_pl19t, contenant_roll):
        """PL 19T (7.5×2.4) avec rolls (0.8×0.6) : rotation incluse."""
        n = max_contenants_par_vehicule(vehicule_pl19t, contenant_roll)
        # Orientation 1 : 0.8×0.6 → 9×4 = 36
        # Orientation 2 : 0.6×0.8 → 12×3 = 36
        assert n == 36

    def test_pl19t_armoires(self, vehicule_pl19t, contenant_armoire):
        """PL 19T avec armoires de linge (1.2×0.6)."""
        n = max_contenants_par_vehicule(vehicule_pl19t, contenant_armoire)
        # Orientation 1: 7.5/1.2=6 cols, 2.4/0.6=4 rows → 24
        # Orientation 2: 7.5/0.6=12 cols, 2.4/1.2=2 rows → 24
        assert n == 24

    def test_vl_petits_contenants(self, vehicule_vl, contenant_petit):
        """VL (3.0×1.8) avec petits contenants (0.4×0.3)."""
        n = max_contenants_par_vehicule(vehicule_vl, contenant_petit)
        # Orientation 1: 3.0/0.4=7 cols, 1.8/0.3=6 rows → 42
        assert n == 42

    def test_capacite_positive(self, vehicule_pl12t, contenant_roll):
        """Le résultat doit toujours être ≥ 0."""
        n = max_contenants_par_vehicule(vehicule_pl12t, contenant_roll)
        assert n >= 0

    def test_contenant_zero_longueur(self, vehicule_pl19t):
        """Contenant avec dimension nulle → 0."""
        from models import Contenant
        c_zero = Contenant(libelle="Zero", longueur=0.0, largeur=0.6,
                           poids_vide=0.01, poids_plein=0.05)
        assert max_contenants_par_vehicule(vehicule_pl19t, c_zero) == 0

    def test_vehicule_surface_nulle(self, contenant_roll):
        """Véhicule de surface nulle → 0."""
        from models import Vehicule
        v = Vehicule(
            type_vehicule="ZERO", stationnement_initial="HSJ",
            longueur=0.0, largeur=0.0, hauteur=0.0, surface_utile=0.0,
            poids_max=1.0, consommation=0.0, cout_carburant=0.0, cout_carbone=0.0,
            hayon=False, temps_mise_quai=0, manu_avec_quai=1,
        )
        assert max_contenants_par_vehicule(v, contenant_roll) == 0


# ---------------------------------------------------------------------------
# check_poids_ok — contrainte poids
# ---------------------------------------------------------------------------

class TestCheckPoidsOk:
    """Tests de la vérification de la contrainte de poids."""

    def test_poids_ok_vide(self, vehicule_vl, contenant_petit):
        """Quelques colis légers → poids total acceptable."""
        # 5 petits colis vides : 5 × 0.005 = 0.025 t ≪ 1.5 t
        result = check_poids_ok(vehicule_vl, [(contenant_petit, 5, False)])
        assert result is True

    def test_poids_ok_plein(self, vehicule_vl, contenant_petit):
        """5 colis pleins : 5 × 0.020 = 0.1 t < 1.5 t."""
        result = check_poids_ok(vehicule_vl, [(contenant_petit, 5, True)])
        assert result is True

    def test_poids_depasse(self, vehicule_vl, contenant_armoire):
        """Armoires pleines → poids dépasse la limite du VL."""
        # 1 armoire pleine = 0.12 t × 20 = 2.4 t > 1.5 t (limite VL)
        result = check_poids_ok(vehicule_vl, [(contenant_armoire, 20, True)])
        assert result is False

    def test_poids_exactement_limite(self, vehicule_pl19t, contenant_roll):
        """Poids exactement égal à la limite → ok."""
        # 1 roll vide = 0.025 t → combien pour atteindre 12 t ?
        # 12 / 0.025 = 480 rolls vides → exactement 12 t
        result = check_poids_ok(vehicule_pl19t, [(contenant_roll, 480, False)])
        assert result is True

    def test_poids_juste_au_dessus(self, vehicule_pl19t, contenant_roll):
        """Poids légèrement au-dessus de la limite → ko."""
        result = check_poids_ok(vehicule_pl19t, [(contenant_roll, 481, False)])
        assert result is False

    def test_liste_vide(self, vehicule_pl19t):
        """Aucun chargement → toujours ok."""
        result = check_poids_ok(vehicule_pl19t, [])
        assert result is True

    def test_multiples_contenants(self, vehicule_vl, contenant_petit, contenant_roll):
        """Mix de contenants légers dans un VL."""
        charges = [(contenant_petit, 3, True), (contenant_roll, 0, False)]
        result = check_poids_ok(vehicule_vl, charges)
        assert result is True


# ---------------------------------------------------------------------------
# taux_remplissage_surface
# ---------------------------------------------------------------------------

class TestTauxRemplissageSurface:
    """Tests du taux de remplissage surfacique."""

    def test_vide(self, vehicule_pl19t):
        t = taux_remplissage_surface(vehicule_pl19t, [])
        assert t == 0.0

    def test_taux_complet(self, vehicule_pl19t, contenant_roll):
        """36 rolls dans PL19T = surface exactement couverte."""
        n = max_contenants_par_vehicule(vehicule_pl19t, contenant_roll)
        # taux = (n × 0.48) / (7.5 × 2.4)
        charges = [(contenant_roll, n)]
        t = taux_remplissage_surface(vehicule_pl19t, charges)
        assert 0.0 < t <= 1.0 + 1e-6

    def test_taux_entre_zero_et_un(self, vehicule_pl19t, contenant_roll):
        charges = [(contenant_roll, 10)]
        t = taux_remplissage_surface(vehicule_pl19t, charges)
        assert 0.0 < t <= 1.0

    def test_surface_zero_vehicule(self, contenant_roll):
        """Véhicule de surface nulle → taux 0."""
        from models import Vehicule
        v = Vehicule(
            type_vehicule="ZERO", stationnement_initial="HSJ",
            longueur=0.0, largeur=0.0, hauteur=0.0, surface_utile=0.0,
            poids_max=1.0, consommation=0.0, cout_carburant=0.0, cout_carbone=0.0,
            hayon=False, temps_mise_quai=0, manu_avec_quai=1,
        )
        assert taux_remplissage_surface(v, [(contenant_roll, 5)]) == 0.0


# ---------------------------------------------------------------------------
# eclater_flux_volumineux
# ---------------------------------------------------------------------------

class TestEclaterFluxVolumineux:
    """Tests de l'éclatement des flux dépassant la capacité d'un véhicule."""

    def test_flux_inferieur_capacite(
        self, vehicule_pl19t, contenant_roll, flux_blanchisserie_propre
    ):
        """Flux de 10 contenants dans un véhicule de cap. 36 → pas d'éclatement."""
        result = eclater_flux_volumineux(flux_blanchisserie_propre, vehicule_pl19t, contenant_roll)
        assert len(result) == 1
        assert result[0] == (10, True)

    def test_flux_exactement_capacite(
        self, vehicule_pl19t, contenant_roll
    ):
        """Flux de 36 contenants pour un véhicule de cap. 36 → 1 voyage plein."""
        from models import Flux
        f = Flux(
            id_flux=10, site_depart="HSJ", site_arrivee="HLS",
            fonction_support="BLANCHISSERIE",
            type_contenant="Rolls linge sale",
            quantite=36,
            statut_plein_vide="Plein", statut_propre_sale="Sale",
            heure_dispo=360, heure_max_livraison=600,
        )
        result = eclater_flux_volumineux(f, vehicule_pl19t, contenant_roll)
        assert len(result) == 1
        assert result[0] == (36, True)

    def test_flux_deux_voyages_pleins(
        self, vehicule_pl19t, contenant_roll
    ):
        """Flux de 72 = 2 × cap(36) → 2 voyages pleins."""
        from models import Flux
        f = Flux(
            id_flux=11, site_depart="HSJ", site_arrivee="HLS",
            fonction_support="BLANCHISSERIE",
            type_contenant="Rolls linge sale",
            quantite=72,
            statut_plein_vide="Plein", statut_propre_sale="Sale",
            heure_dispo=360, heure_max_livraison=600,
        )
        result = eclater_flux_volumineux(f, vehicule_pl19t, contenant_roll)
        assert len(result) == 2
        assert result[0] == (36, False)
        assert result[1] == (36, False)

    def test_flux_avec_reste(
        self, vehicule_pl19t, contenant_roll
    ):
        """Flux de 50 = 1×36 + 14 reste → 1 voyage plein + 1 reste."""
        from models import Flux
        f = Flux(
            id_flux=12, site_depart="HSJ", site_arrivee="HLS",
            fonction_support="BLANCHISSERIE",
            type_contenant="Rolls linge sale",
            quantite=50,
            statut_plein_vide="Plein", statut_propre_sale="Sale",
            heure_dispo=360, heure_max_livraison=600,
        )
        result = eclater_flux_volumineux(f, vehicule_pl19t, contenant_roll)
        assert len(result) == 2
        assert result[0] == (36, False)
        assert result[1] == (14, True)

    def test_somme_quantites_conservee(
        self, vehicule_pl19t, contenant_roll
    ):
        """La somme des quantités éclatées doit égaler la quantité initiale."""
        from models import Flux
        for qty in [1, 10, 36, 37, 72, 100, 200]:
            f = Flux(
                id_flux=qty, site_depart="HSJ", site_arrivee="HLS",
                fonction_support="BLANCHISSERIE",
                type_contenant="Rolls linge sale",
                quantite=qty,
                statut_plein_vide="Plein", statut_propre_sale="Sale",
                heure_dispo=360, heure_max_livraison=600,
            )
            result = eclater_flux_volumineux(f, vehicule_pl19t, contenant_roll)
            total = sum(n for n, _ in result)
            assert total == qty, f"Quantité {qty} : somme éclatée = {total}"

    def test_dernier_voyage_est_reste(
        self, vehicule_pl19t, contenant_roll
    ):
        """Le dernier voyage d'un éclatement est toujours le reste (est_dernier_reste=True)."""
        from models import Flux
        for qty in [10, 37, 73, 150]:
            f = Flux(
                id_flux=qty, site_depart="HSJ", site_arrivee="HLS",
                fonction_support="BLANCHISSERIE",
                type_contenant="Rolls linge sale",
                quantite=qty,
                statut_plein_vide="Plein", statut_propre_sale="Sale",
                heure_dispo=360, heure_max_livraison=600,
            )
            result = eclater_flux_volumineux(f, vehicule_pl19t, contenant_roll)
            # Le dernier élément doit toujours être True (reste)
            assert result[-1][1] is True, f"Dernier voyage pour qty={qty} devrait être True"
