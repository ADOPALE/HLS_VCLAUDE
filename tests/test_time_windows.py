"""
test_time_windows.py — Tests des calculs de fenêtres horaires OptiFLUX.

Couvre : minutes_to_hhmm, hhmm_to_minutes, calcul_t_min,
         appliquer_facteur_circulation, detecter_flux_infaisables.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from time_windows import (
    minutes_to_hhmm,
    hhmm_to_minutes,
    calcul_t_min,
    appliquer_facteur_circulation,
    detecter_flux_infaisables,
)


# ---------------------------------------------------------------------------
# CONVERSIONS HORAIRES
# ---------------------------------------------------------------------------

class TestMinutesToHHMM:
    """Tests de la conversion minutes → HH:MM."""

    def test_zero(self):
        assert minutes_to_hhmm(0) == "00:00"

    def test_heure_pile(self):
        assert minutes_to_hhmm(60) == "01:00"

    def test_heure_trente(self):
        assert minutes_to_hhmm(90) == "01:30"

    def test_debut_journee_6h(self):
        assert minutes_to_hhmm(360) == "06:00"

    def test_milieu_matinee_8h30(self):
        assert minutes_to_hhmm(510) == "08:30"

    def test_minuit_1440(self):
        assert minutes_to_hhmm(1440) == "24:00"

    def test_format_zero_padde(self):
        """Les heures et minutes doivent être sur 2 chiffres."""
        assert minutes_to_hhmm(5) == "00:05"
        assert minutes_to_hhmm(65) == "01:05"


class TestHHMMToMinutes:
    """Tests de la conversion HH:MM → minutes."""

    def test_minuit(self):
        assert hhmm_to_minutes("00:00") == 0

    def test_une_heure(self):
        assert hhmm_to_minutes("01:00") == 60

    def test_six_heures(self):
        assert hhmm_to_minutes("06:00") == 360

    def test_huit_trente(self):
        assert hhmm_to_minutes("08:30") == 510

    def test_vingt_et_une_heures(self):
        assert hhmm_to_minutes("21:00") == 1260


class TestConversionRoundTrip:
    """Vérification de la symétrie des deux fonctions de conversion."""

    @pytest.mark.parametrize("minutes", [0, 5, 30, 60, 360, 390, 510, 720, 1080, 1259])
    def test_round_trip_minutes(self, minutes):
        assert hhmm_to_minutes(minutes_to_hhmm(minutes)) == minutes

    @pytest.mark.parametrize("hhmm", ["00:00", "06:00", "07:30", "08:00", "12:00", "18:45", "21:00"])
    def test_round_trip_hhmm(self, hhmm):
        assert minutes_to_hhmm(hhmm_to_minutes(hhmm)) == hhmm


# ---------------------------------------------------------------------------
# CALCUL T_MIN
# ---------------------------------------------------------------------------

class TestCalculTMin:
    """Tests du calcul du temps minimal de transport."""

    def test_t_min_deux_sites_avec_quai(
        self, vehicule_pl19t, site_avec_quai, site_hls,
        flux_blanchisserie_propre, matrix_dur
    ):
        """T_min pour un flux entre deux sites avec quai."""
        sites = {"HSJ": site_avec_quai, "HLS": site_hls}
        t = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur)
        # mise_quai_dep(5) + chargement(10×2=20) + trajet(25) + mise_quai_arr(5) + dechargement(10×2=20)
        expected = 5 + 20 + 25 + 5 + 20
        assert t == expected, f"T_min attendu {expected}, obtenu {t}"

    def test_t_min_site_sans_quai_vl(
        self, vehicule_vl, site_avec_quai, site_sans_quai,
        flux_pharmacie_mixte, matrix_dur
    ):
        """T_min pour un flux vers un site sans quai, avec VL hayon."""
        sites = {"HSJ": site_avec_quai, "HGRL": site_sans_quai}
        t = calcul_t_min(flux_pharmacie_mixte, vehicule_vl, sites, matrix_dur)
        # mise_quai_dep(3) + chargement(5×3=15) + trajet(30) + pas_quai_arr(0) + dechargement(5×5=25)
        expected = 3 + 15 + 30 + 0 + 25
        assert t == expected, f"T_min attendu {expected}, obtenu {t}"

    def test_t_min_site_inconnu(
        self, vehicule_pl19t, flux_blanchisserie_propre, matrix_dur
    ):
        """Site inconnu → temps de mise à quai 0."""
        sites = {}  # aucun site renseigné
        t = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur)
        # Pas de quai, manu sans quai = None → 0 partout, trajet = 25
        # Mais PL19T a manu_sans_quai=None donc _get_manu retourne 0
        assert isinstance(t, int)
        assert t >= 0

    def test_t_min_zero_trajet(
        self, vehicule_pl19t, site_avec_quai, flux_blanchisserie_propre
    ):
        """Sites côte à côte (durée 0) → trajet ne contribue pas au T_min."""
        sites = {"HSJ": site_avec_quai, "HLS": site_avec_quai}
        matrix_zero = {"HSJ": {"HLS": 0}, "HLS": {"HSJ": 0}}
        f = flux_blanchisserie_propre.model_copy(update={"quantite": 1})
        t = calcul_t_min(f, vehicule_pl19t, sites, matrix_zero)
        # quai + manu_quai×1 + 0 + quai + manu_quai×1
        expected = 5 + 2 + 0 + 5 + 2
        assert t == expected

    def test_t_min_avec_facteur_circulation(
        self, vehicule_pl19t, site_avec_quai, site_hls,
        flux_blanchisserie_propre, matrix_dur
    ):
        """Le facteur de circulation augmente le temps de trajet."""
        sites = {"HSJ": site_avec_quai, "HLS": site_hls}
        t_sans = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur, 0)
        t_avec = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur, 20)
        assert t_avec > t_sans

    def test_t_min_facteur_zero_invariant(
        self, vehicule_pl19t, site_avec_quai, site_hls,
        flux_blanchisserie_propre, matrix_dur
    ):
        """Facteur de circulation 0 ne modifie pas le T_min."""
        sites = {"HSJ": site_avec_quai, "HLS": site_hls}
        t1 = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur, 0)
        t2 = calcul_t_min(flux_blanchisserie_propre, vehicule_pl19t, sites, matrix_dur, 0.0)
        assert t1 == t2


# ---------------------------------------------------------------------------
# FACTEUR DE CIRCULATION
# ---------------------------------------------------------------------------

class TestAppliquerFacteurCirculation:
    """Tests de l'application du facteur de circulation sur les matrices."""

    def test_facteur_zero_invariant(self, matrix_dur):
        result = appliquer_facteur_circulation(matrix_dur, 0)
        assert result == matrix_dur

    def test_facteur_vingt_pourcent(self, matrix_dur):
        result = appliquer_facteur_circulation(matrix_dur, 20)
        # Durée HSJ → HLS = 25 × 1.2 = 30
        assert result["HSJ"]["HLS"] == 30

    def test_durée_nulle_reste_nulle(self, matrix_dur):
        """Les durées nulles (sites identiques) ne doivent pas être modifiées."""
        result = appliquer_facteur_circulation(matrix_dur, 50)
        assert result["HSJ"]["HSJ"] == 0
        assert result["HLS"]["HLS"] == 0

    def test_retourne_nouvelle_matrice(self, matrix_dur):
        """La fonction retourne une nouvelle matrice, sans modifier l'originale."""
        original_val = matrix_dur["HSJ"]["HLS"]
        result = appliquer_facteur_circulation(matrix_dur, 10)
        assert matrix_dur["HSJ"]["HLS"] == original_val  # original inchangé
        assert result["HSJ"]["HLS"] != original_val

    def test_toutes_durees_augmentees(self, matrix_dur):
        result = appliquer_facteur_circulation(matrix_dur, 30)
        for dep, row in matrix_dur.items():
            for arr, dur in row.items():
                if dur > 0:
                    assert result[dep][arr] > dur
                else:
                    assert result[dep][arr] == 0


# ---------------------------------------------------------------------------
# DÉTECTION FLUX INFAISABLES
# ---------------------------------------------------------------------------

class TestDetecterFluxInfaisables:
    """Tests de détection des flux dont la fenêtre horaire est insuffisante."""

    def test_flux_faisable(
        self, vehicules_dict, sites_dict, matrix_dur,
        flux_blanchisserie_propre
    ):
        """Un flux avec fenêtre suffisante ne doit pas être signalé."""
        # Flux: heure_dispo=360, heure_max=480 → fenêtre=120 min
        # T_min PL19T: 5+20+25+5+20 = 75 min < 120 → faisable
        infaisables = detecter_flux_infaisables(
            [flux_blanchisserie_propre], vehicules_dict, sites_dict, matrix_dur
        )
        assert len(infaisables) == 0

    def test_flux_infaisable_fenetre_trop_courte(
        self, vehicule_pl19t, site_avec_quai, site_hls, matrix_dur
    ):
        """Un flux avec fenêtre trop courte doit être signalé."""
        from models import Flux
        # Fenêtre très courte : seulement 10 minutes (heure_dispo=360, max=370)
        flux = Flux(
            id_flux=99,
            site_depart="HSJ",
            site_arrivee="HLS",
            fonction_support="BLANCHISSERIE",
            type_contenant="Armoires de linge",
            quantite=10,
            statut_plein_vide="Plein",
            statut_propre_sale="Propre",
            heure_dispo=360,
            heure_max_livraison=370,  # seulement 10 min
        )
        vehicules = {"PL 19T": vehicule_pl19t}
        sites = {"HSJ": site_avec_quai, "HLS": site_hls}
        infaisables = detecter_flux_infaisables([flux], vehicules, sites, matrix_dur)
        assert len(infaisables) == 1
        assert infaisables[0]["id_flux"] == 99
        assert infaisables[0]["t_min"] > infaisables[0]["fenetre_disponible"]

    def test_flux_sans_vehicule_compatible(
        self, vehicule_pl19t, site_avec_quai, site_sans_quai, matrix_dur
    ):
        """Un flux dont aucun véhicule n'est compatible est signalé infaisable."""
        from models import Flux
        # PL19T ne peut pas aller sur site sans quai
        flux = Flux(
            id_flux=98,
            site_depart="HSJ",
            site_arrivee="HGRL",
            fonction_support="BLANCHISSERIE",
            type_contenant="Armoires de linge",
            quantite=5,
            statut_plein_vide="Plein",
            statut_propre_sale="Propre",
            heure_dispo=360,
            heure_max_livraison=600,
        )
        vehicules = {"PL 19T": vehicule_pl19t}
        sites = {"HSJ": site_avec_quai, "HGRL": site_sans_quai}
        infaisables = detecter_flux_infaisables([flux], vehicules, sites, matrix_dur)
        assert len(infaisables) == 1
        assert infaisables[0]["raison"] == "Aucun véhicule compatible avec ce flux"

    def test_liste_vide(self, vehicules_dict, sites_dict, matrix_dur):
        """Aucun flux → aucun infaisable."""
        result = detecter_flux_infaisables([], vehicules_dict, sites_dict, matrix_dur)
        assert result == []
