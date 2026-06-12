"""
test_rh.py — Tests des validations RH (Ressources Humaines) OptiFLUX.

Couvre : _check_rh (via validate_all), paramètres RH par défaut,
         cohérence des vacations, pauses et plages horaires.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from validators import validate_all, _check_rh


# ---------------------------------------------------------------------------
# FIXTURES LOCALES
# ---------------------------------------------------------------------------

@pytest.fixture
def rh_valide():
    """Paramètres RH valides : vacation 7h30, pause 30 min, 6h–21h."""
    return {
        "vacation_duration": 450,   # 7h30
        "pause_duration": 30,        # 30 min
        "start_min": 360,            # 06:00
        "end_max": 1260,             # 21:00
    }


@pytest.fixture
def sites_vides():
    return {}


@pytest.fixture
def flux_vide():
    return []


@pytest.fixture
def matrices_vides():
    return {}


# ---------------------------------------------------------------------------
# _check_rh — TESTS UNITAIRES
# ---------------------------------------------------------------------------

class TestCheckRH:
    """Tests unitaires sur _check_rh (appel direct, sans passer par validate_all)."""

    def test_rh_valide_sans_erreur(self, rh_valide):
        errors = []
        _check_rh(rh_valide, errors)
        assert errors == [], f"Erreurs inattendues : {errors}"

    def test_pause_egale_vacation_bloque(self):
        """Pause ≥ vacation → erreur bloquante."""
        rh = {"vacation_duration": 60, "pause_duration": 60, "start_min": 360, "end_max": 1260}
        errors = []
        _check_rh(rh, errors)
        types = [e["type"] for e in errors]
        assert "RH_INCOHERENT" in types

    def test_pause_superieure_vacation_bloque(self):
        """Pause > vacation → erreur bloquante."""
        rh = {"vacation_duration": 60, "pause_duration": 90, "start_min": 360, "end_max": 1260}
        errors = []
        _check_rh(rh, errors)
        assert any(e["type"] == "RH_INCOHERENT" for e in errors)

    def test_vacation_depasse_plage_horaire(self):
        """Heure début + vacation > heure fin → erreur bloquante."""
        rh = {"vacation_duration": 960, "pause_duration": 30, "start_min": 360, "end_max": 1260}
        # 360 + 960 = 1320 > 1260 → erreur
        errors = []
        _check_rh(rh, errors)
        assert any(e["type"] == "RH_INCOHERENT" for e in errors)

    def test_vacation_exactement_dans_plage(self):
        """Heure début + vacation = heure fin → ok (limite acceptée)."""
        rh = {"vacation_duration": 900, "pause_duration": 30, "start_min": 360, "end_max": 1260}
        # 360 + 900 = 1260 = 1260 → ok
        errors = []
        _check_rh(rh, errors)
        assert errors == []

    def test_pause_zero_valide(self):
        """Pause nulle techniquement possible (même si non souhaitable)."""
        rh = {"vacation_duration": 450, "pause_duration": 0, "start_min": 360, "end_max": 1260}
        errors = []
        _check_rh(rh, errors)
        # Pas d'erreur RH si pause=0 < vacation=450
        assert not any(e["type"] == "RH_INCOHERENT" for e in errors)


# ---------------------------------------------------------------------------
# TESTS VIA validate_all — intégration RH
# ---------------------------------------------------------------------------

class TestValidateAllRH:
    """Tests de la validation RH via validate_all (intégration)."""

    def test_rh_defaut_valide(self, sites_vides, flux_vide, matrices_vides):
        """Les paramètres RH par défaut de config.py ne doivent pas générer d'erreurs."""
        result = validate_all(
            rh=config.DEFAULT_RH,
            sites=sites_vides,
            vehicules={},
            contenants={},
            matrix_dur=matrices_vides,
            matrix_dist=matrices_vides,
            flux_brut=flux_vide,
        )
        # Pas d'erreurs de type RH_INCOHERENT
        rh_errors = [e for e in result["errors"] if e["type"] == "RH_INCOHERENT"]
        assert rh_errors == [], f"Erreurs RH inattendues sur config par défaut : {rh_errors}"

    def test_rh_invalide_genere_erreur(self, sites_vides, flux_vide, matrices_vides):
        """Des paramètres RH invalides doivent générer des erreurs bloquantes."""
        rh_invalide = {
            "vacation_duration": 30,
            "pause_duration": 60,   # pause > vacation → erreur
            "start_min": 360,
            "end_max": 1260,
        }
        result = validate_all(
            rh=rh_invalide,
            sites=sites_vides,
            vehicules={},
            contenants={},
            matrix_dur=matrices_vides,
            matrix_dist=matrices_vides,
            flux_brut=flux_vide,
        )
        assert len(result["errors"]) > 0

    def test_validate_all_retourne_structure_attendue(
        self, rh_valide, sites_vides, flux_vide, matrices_vides
    ):
        """validate_all doit toujours retourner un dict avec 'errors' et 'warnings'."""
        result = validate_all(
            rh=rh_valide,
            sites=sites_vides,
            vehicules={},
            contenants={},
            matrix_dur=matrices_vides,
            matrix_dist=matrices_vides,
            flux_brut=flux_vide,
        )
        assert "errors" in result
        assert "warnings" in result
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)


# ---------------------------------------------------------------------------
# TESTS PARAMÈTRES RH PAR DÉFAUT (config.DEFAULT_RH)
# ---------------------------------------------------------------------------

class TestDefaultRH:
    """Tests de cohérence des valeurs DEFAULT_RH définies dans config.py."""

    def test_vacation_duration_positif(self):
        assert config.DEFAULT_RH["vacation_duration"] > 0

    def test_pause_duration_positif(self):
        assert config.DEFAULT_RH["pause_duration"] > 0

    def test_pause_inferieure_vacation(self):
        assert config.DEFAULT_RH["pause_duration"] < config.DEFAULT_RH["vacation_duration"]

    def test_start_min_inferieur_end_max(self):
        assert config.DEFAULT_RH["start_min"] < config.DEFAULT_RH["end_max"]

    def test_vacation_tient_dans_plage(self):
        rh = config.DEFAULT_RH
        assert rh["start_min"] + rh["vacation_duration"] <= rh["end_max"]

    def test_prise_et_fin_poste_inclus_dans_vacation(self):
        """La vacation doit être assez longue pour inclure prise+fin de poste."""
        vac = config.DEFAULT_RH["vacation_duration"]
        overhead = config.PRISE_DE_POSTE_MIN + config.FIN_DE_POSTE_MIN
        assert vac > overhead, f"Vacation {vac} min trop courte pour l'overhead {overhead} min"

    def test_pause_inferieure_vacation_moins_overhead(self):
        """La pause doit tenir dans la vacation utile (après prise/fin de poste)."""
        vac = config.DEFAULT_RH["vacation_duration"]
        pause = config.DEFAULT_RH["pause_duration"]
        overhead = config.PRISE_DE_POSTE_MIN + config.FIN_DE_POSTE_MIN
        assert pause < vac - overhead


# ---------------------------------------------------------------------------
# TESTS DE CONTRAINTES OPÉRATIONNELLES RH
# ---------------------------------------------------------------------------

class TestContraintesOperationnelles:
    """Tests des contraintes opérationnelles liées aux paramètres RH."""

    def test_desinfection_dans_vacation(self):
        """La durée de désinfection doit être compatible avec une vacation."""
        vac = config.DEFAULT_RH["vacation_duration"]
        assert config.DESINFECTION_DURATION < vac

    def test_pause_window_heures_coherent(self):
        """La fenêtre de pause (±60 min) doit être en minutes positives."""
        assert config.PAUSE_WINDOW_HOURS > 0

    def test_rh_semaine_et_weekend_possible(self):
        """Les 7 jours doivent être accessibles dans DAY_COLUMNS."""
        for day_idx in range(7):
            assert day_idx in config.DAY_COLUMNS
            assert day_idx in config.DAY_NAMES

    def test_jours_semaine_vs_weekend(self):
        """5 jours ouvrés + 2 jours weekend."""
        jours_ouvres = set(range(7)) - config.WEEKEND_DAYS
        assert len(jours_ouvres) == 5
        assert len(config.WEEKEND_DAYS) == 2
