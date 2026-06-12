"""
test_import.py — Tests d'import et de structure de données OptiFLUX.

Vérifie que tous les modules sont importables, que les modèles Pydantic
s'instancient correctement et que les constantes config sont cohérentes.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# TESTS D'IMPORT DES MODULES
# ---------------------------------------------------------------------------

class TestImports:
    """Vérifie que tous les modules principaux sont importables sans erreur."""

    def test_import_config(self):
        import config
        assert hasattr(config, "REQUIRED_SHEETS")

    def test_import_models(self):
        from models import Site, Vehicule, Contenant, Flux, Tournee, PosteChaufeur, ResultatJour
        assert all([Site, Vehicule, Contenant, Flux, Tournee, PosteChaufeur, ResultatJour])

    def test_import_data_loader(self):
        import data_loader
        assert hasattr(data_loader, "load_all")

    def test_import_validators(self):
        import validators
        assert hasattr(validators, "validate_all")

    def test_import_preprocessing(self):
        import preprocessing
        assert hasattr(preprocessing, "get_active_flux")

    def test_import_capacity(self):
        import capacity
        assert hasattr(capacity, "max_contenants_par_vehicule")

    def test_import_compatibility(self):
        import compatibility
        assert hasattr(compatibility, "vehicule_compatible_flux")

    def test_import_time_windows(self):
        import time_windows
        assert hasattr(time_windows, "calcul_t_min")
        assert hasattr(time_windows, "minutes_to_hhmm")
        assert hasattr(time_windows, "hhmm_to_minutes")

    def test_import_optimizer(self):
        import optimizer
        assert hasattr(optimizer, "optimizer_run")

    def test_import_route_builder(self):
        import route_builder
        assert hasattr(route_builder, "build_route_steps")

    def test_import_driver_scheduler(self):
        import driver_scheduler
        assert hasattr(driver_scheduler, "affecter_postes")

    def test_import_dock_scheduler(self):
        import dock_scheduler
        assert hasattr(dock_scheduler, "build_dock_planning")

    def test_import_visualization(self):
        import visualization
        assert hasattr(visualization, "make_gantt_postes")

    def test_import_outputs(self):
        import outputs
        assert hasattr(outputs, "generate_excel_results")


# ---------------------------------------------------------------------------
# TESTS CONFIG
# ---------------------------------------------------------------------------

class TestConfig:
    """Vérifie la cohérence des constantes de configuration."""

    def test_required_sheets(self):
        import config
        expected = {"param RH", "param Sites", "param Véhicules", "param Contenants",
                    "matrice Durée", "matrice Dist", "LISTES", "M flux"}
        assert set(config.REQUIRED_SHEETS) == expected

    def test_day_columns_count(self):
        import config
        assert len(config.DAY_COLUMNS) == 7, "Il doit y avoir exactement 7 jours"

    def test_day_names_count(self):
        import config
        assert len(config.DAY_NAMES) == 7

    def test_weekend_days(self):
        import config
        assert config.WEEKEND_DAYS == {5, 6}

    def test_default_rh_coherent(self):
        import config
        rh = config.DEFAULT_RH
        assert rh["pause_duration"] < rh["vacation_duration"], \
            "La pause doit être plus courte que la vacation"
        assert rh["start_min"] + rh["vacation_duration"] <= rh["end_max"], \
            "Une vacation doit tenir dans la plage horaire"

    def test_prise_fin_poste_positifs(self):
        import config
        assert config.PRISE_DE_POSTE_MIN > 0
        assert config.FIN_DE_POSTE_MIN > 0

    def test_desinfection_duration_positif(self):
        import config
        assert config.DESINFECTION_DURATION > 0

    def test_sanitaire_constants(self):
        import config
        assert config.SANITAIRE_PROPRE != config.SANITAIRE_SALE

    def test_export_sheets_count(self):
        import config
        assert len(config.EXPORT_SHEETS) == 9, "L'export doit comporter 9 onglets"

    def test_gantt_colors_keys(self):
        import config
        expected_ops = {
            config.OP_PRISE_POSTE, config.OP_FIN_POSTE, config.OP_TRAJET_VIDE,
            config.OP_TRAJET_CHARGE, config.OP_CHARGEMENT, config.OP_DECHARGEMENT,
            config.OP_MISE_A_QUAI, config.OP_PAUSE, config.OP_DESINFECTION,
            config.OP_ATTENTE, config.OP_INOCCUPE,
        }
        assert set(config.GANTT_COLORS.keys()) == expected_ops


# ---------------------------------------------------------------------------
# TESTS INSTANCIATION MODÈLES
# ---------------------------------------------------------------------------

class TestModelsInstanciation:
    """Vérifie que les modèles Pydantic s'instancient et valident correctement."""

    def test_site_minimal(self):
        from models import Site
        s = Site(libelle="TEST", presence_quai=True)
        assert s.libelle == "TEST"
        assert s.presence_quai is True
        assert s.capacite_quai == 3  # valeur par défaut

    def test_site_sans_quai(self):
        from models import Site
        s = Site(libelle="SATELITE", presence_quai=False, capacite_quai=0)
        assert not s.presence_quai

    def test_vehicule_peut_operer_sans_quai_hayon_ok(self):
        from models import Vehicule
        v = Vehicule(
            type_vehicule="VL",
            stationnement_initial="HSJ",
            longueur=3.0, largeur=1.8, hauteur=1.8,
            surface_utile=5.4, poids_max=1.5,
            consommation=10.0, cout_carburant=0.15, cout_carbone=0.026,
            hayon=True,
            temps_mise_quai=3, manu_sans_quai=5, manu_avec_quai=3,
        )
        assert v.peut_operer_sans_quai is True

    def test_vehicule_peut_operer_sans_quai_sans_hayon(self):
        from models import Vehicule
        v = Vehicule(
            type_vehicule="PL",
            stationnement_initial="HSJ",
            longueur=7.5, largeur=2.4, hauteur=2.5,
            surface_utile=18.0, poids_max=12.0,
            consommation=28.0, cout_carburant=0.42, cout_carbone=0.074,
            hayon=False,
            temps_mise_quai=5, manu_sans_quai=None, manu_avec_quai=2,
        )
        assert v.peut_operer_sans_quai is False

    def test_vehicule_peut_operer_sans_quai_hayon_nc(self):
        """Hayon présent mais manu_sans_quai = NC → ne peut pas opérer sans quai."""
        from models import Vehicule
        v = Vehicule(
            type_vehicule="SEMI",
            stationnement_initial="HSJ",
            longueur=12.0, largeur=2.4, hauteur=2.5,
            surface_utile=28.8, poids_max=18.0,
            consommation=35.0, cout_carburant=0.52, cout_carbone=0.090,
            hayon=True,  # hayon présent mais NC
            temps_mise_quai=10, manu_sans_quai=None, manu_avec_quai=2,
        )
        assert v.peut_operer_sans_quai is False

    def test_contenant_surface(self):
        from models import Contenant
        c = Contenant(libelle="Roll", longueur=0.8, largeur=0.6,
                      poids_vide=0.025, poids_plein=0.080)
        assert abs(c.surface - 0.48) < 1e-9

    def test_flux_champs_requis(self):
        from models import Flux
        f = Flux(
            id_flux=42,
            site_depart="HSJ",
            site_arrivee="HLS",
            fonction_support="BLANCHISSERIE",
            type_contenant="Armoires de linge",
            quantite=5,
            statut_plein_vide="Plein",
            statut_propre_sale="Propre",
            heure_dispo=360,
            heure_max_livraison=480,
        )
        assert f.id_flux == 42
        assert f.transport_mixte is False
        assert f.urgent is False

    def test_resultat_jour_defauts(self):
        from models import ResultatJour
        r = ResultatJour(jour="Lundi", jour_idx=0)
        assert r.taux_service == 0.0
        assert r.nb_vehicules == 0
        assert r.flux_transportes == []
