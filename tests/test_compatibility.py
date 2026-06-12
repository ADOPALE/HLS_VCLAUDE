"""
test_compatibility.py — Tests des règles de compatibilité OptiFLUX.

Couvre : vehicule_compatible_flux, peut_grouper_flux, vehicule_peut_charger,
         get_vehicules_compatibles_flux, etat_sanitaire_apres_chargement.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from compatibility import (
    vehicule_compatible_flux,
    peut_grouper_flux,
    vehicule_peut_charger,
    get_vehicules_compatibles_flux,
    etat_sanitaire_apres_chargement,
)


# ---------------------------------------------------------------------------
# vehicule_compatible_flux
# ---------------------------------------------------------------------------

class TestVehiculeCompatibleFlux:
    """Tests de compatibilité véhicule ↔ flux."""

    def test_pl19t_compatible_flux_avec_quai(
        self, vehicule_pl19t, flux_blanchisserie_propre, sites_dict
    ):
        """PL19T compatible avec un flux entre deux sites avec quai."""
        assert vehicule_compatible_flux(vehicule_pl19t, flux_blanchisserie_propre, sites_dict)

    def test_pl19t_incompatible_site_sans_quai(
        self, vehicule_pl19t, flux_pharmacie_mixte, sites_dict
    ):
        """PL19T (sans hayon, manu_sans_quai=None) incompatible avec site sans quai."""
        assert not vehicule_compatible_flux(vehicule_pl19t, flux_pharmacie_mixte, sites_dict)

    def test_vl_compatible_site_sans_quai(
        self, vehicule_vl, flux_pharmacie_mixte, sites_dict
    ):
        """VL (hayon + manu_sans_quai renseigné) compatible avec site sans quai."""
        assert vehicule_compatible_flux(vehicule_vl, flux_pharmacie_mixte, sites_dict)

    def test_incompatibilite_contenant(
        self, vehicule_vl, flux_blanchisserie_propre, sites_dict
    ):
        """VL n'est pas compatible avec les armoires de linge."""
        # vehicule_vl.compat_contenants["Armoires de linge"] n'est pas défini → False
        assert not vehicule_compatible_flux(vehicule_vl, flux_blanchisserie_propre, sites_dict)

    def test_site_inconnu_incompatible(
        self, vehicule_pl19t, flux_blanchisserie_propre
    ):
        """Site inconnu dans le dict → incompatible."""
        assert not vehicule_compatible_flux(vehicule_pl19t, flux_blanchisserie_propre, {})

    def test_vehicule_incompatible_avec_site(
        self, vehicule_pl19t, sites_dict
    ):
        """PL19T non listé dans compat_vehicules d'un site → incompatible."""
        from models import Flux, Site
        site_interdit = Site(
            libelle="SITE_X",
            presence_quai=True,
            compat_vehicules={"VL (UTILITAIRE)": True},  # PL19T absent
        )
        sites = {**sites_dict, "SITE_X": site_interdit}
        flux = Flux(
            id_flux=99, site_depart="HSJ", site_arrivee="SITE_X",
            fonction_support="MAGASIN",
            type_contenant="Armoires de linge",
            quantite=5,
            statut_plein_vide="Plein", statut_propre_sale="Propre",
            heure_dispo=360, heure_max_livraison=600,
        )
        assert not vehicule_compatible_flux(vehicule_pl19t, flux, sites)

    def test_vehicule_inactif_non_considere(
        self, vehicule_pl19t, flux_blanchisserie_propre, sites_dict
    ):
        """Un véhicule inactif ne doit pas être proposé par get_vehicules_compatibles_flux."""
        veh_inactif = vehicule_pl19t.model_copy(update={"actif": False})
        vehicules = {"PL 19T": veh_inactif}
        compatibles = get_vehicules_compatibles_flux(flux_blanchisserie_propre, vehicules, sites_dict)
        assert "PL 19T" not in compatibles


# ---------------------------------------------------------------------------
# peut_grouper_flux
# ---------------------------------------------------------------------------

class TestPeutGrouperFlux:
    """Tests des règles de regroupement de flux dans un même véhicule."""

    def test_meme_statut_propre(
        self, flux_blanchisserie_propre, flux_pharmacie_mixte
    ):
        """Deux flux propres → toujours groupables."""
        assert peut_grouper_flux(flux_blanchisserie_propre, flux_pharmacie_mixte)

    def test_meme_statut_sale(self):
        """Deux flux sales → toujours groupables."""
        from models import Flux
        f1 = Flux(id_flux=1, site_depart="A", site_arrivee="B",
                  fonction_support="BLANCHISSERIE", type_contenant="Rolls linge sale",
                  quantite=5, statut_plein_vide="Plein", statut_propre_sale="Sale",
                  heure_dispo=360, heure_max_livraison=600)
        f2 = Flux(id_flux=2, site_depart="A", site_arrivee="C",
                  fonction_support="BLANCHISSERIE", type_contenant="Rolls linge sale",
                  quantite=3, statut_plein_vide="Plein", statut_propre_sale="Sale",
                  heure_dispo=360, heure_max_livraison=600)
        assert peut_grouper_flux(f1, f2)

    def test_mixte_interdit_flux1(self, flux_blanchisserie_sale):
        """Flux propre avec transport_mixte=False + flux sale → interdit."""
        from models import Flux
        f_propre_strict = Flux(
            id_flux=10, site_depart="A", site_arrivee="B",
            fonction_support="PHARMACIE", type_contenant="Petit contenant/colis",
            quantite=3, statut_plein_vide="Plein", statut_propre_sale="Propre",
            heure_dispo=360, heure_max_livraison=600,
            transport_mixte=False,
        )
        assert not peut_grouper_flux(f_propre_strict, flux_blanchisserie_sale)

    def test_mixte_autorise_sans_exclusion(
        self, flux_blanchisserie_sale
    ):
        """Deux flux de statuts différents avec transport_mixte=True → groupables si pas d'exclusion."""
        from models import Flux
        f_propre = Flux(
            id_flux=20, site_depart="A", site_arrivee="B",
            fonction_support="MAGASIN", type_contenant="Palette",
            quantite=2, statut_plein_vide="Plein", statut_propre_sale="Propre",
            heure_dispo=360, heure_max_livraison=600,
            transport_mixte=True, regle_exclusion=None,
        )
        f_sale = flux_blanchisserie_sale.model_copy(update={"transport_mixte": True})
        assert peut_grouper_flux(f_propre, f_sale)

    def test_regle_exclusion_bloque(self, flux_pharmacie_mixte, flux_blanchisserie_sale):
        """flux_pharmacie_mixte a regle_exclusion='Sale' → ne peut pas cohabiter avec du sale."""
        f_sale = flux_blanchisserie_sale.model_copy(update={"transport_mixte": True})
        assert not peut_grouper_flux(flux_pharmacie_mixte, f_sale)

    def test_symetrie_peut_grouper(self, flux_blanchisserie_propre, flux_blanchisserie_sale):
        """Le résultat doit être symétrique."""
        r1 = peut_grouper_flux(flux_blanchisserie_propre, flux_blanchisserie_sale)
        r2 = peut_grouper_flux(flux_blanchisserie_sale, flux_blanchisserie_propre)
        assert r1 == r2


# ---------------------------------------------------------------------------
# vehicule_peut_charger
# ---------------------------------------------------------------------------

class TestVehiculePeutCharger:
    """Tests de la vérification du chargement en tenant compte de l'état sanitaire."""

    def test_vehicule_propre_charge_propre(self, vehicule_pl19t, flux_blanchisserie_propre):
        """Véhicule propre peut charger du propre."""
        assert vehicule_peut_charger(
            vehicule_pl19t, flux_blanchisserie_propre,
            config.SANITAIRE_PROPRE, []
        )

    def test_vehicule_propre_charge_sale(self, vehicule_pl19t, flux_blanchisserie_sale):
        """Véhicule propre peut charger du sale (devient sale ensuite)."""
        assert vehicule_peut_charger(
            vehicule_pl19t, flux_blanchisserie_sale,
            config.SANITAIRE_PROPRE, []
        )

    def test_vehicule_sale_ne_charge_pas_propre(self, vehicule_pl19t, flux_blanchisserie_propre):
        """Véhicule sale NE PEUT PAS charger du propre."""
        assert not vehicule_peut_charger(
            vehicule_pl19t, flux_blanchisserie_propre,
            config.SANITAIRE_SALE, []
        )

    def test_vehicule_sale_charge_sale(self, vehicule_pl19t, flux_blanchisserie_sale):
        """Véhicule sale peut charger du sale."""
        assert vehicule_peut_charger(
            vehicule_pl19t, flux_blanchisserie_sale,
            config.SANITAIRE_SALE, []
        )

    def test_mixite_bloquee_par_deja_charges(
        self, vehicule_vl, flux_pharmacie_mixte, flux_blanchisserie_sale
    ):
        """Avec un flux sale déjà chargé et règle d'exclusion → impossible de charger un flux propre excluant le sale."""
        # flux_pharmacie_mixte a regle_exclusion="Sale"
        # → impossible si un flux sale est déjà chargé
        assert not vehicule_peut_charger(
            vehicule_vl, flux_pharmacie_mixte,
            config.SANITAIRE_PROPRE,
            [flux_blanchisserie_sale],
        )


# ---------------------------------------------------------------------------
# etat_sanitaire_apres_chargement
# ---------------------------------------------------------------------------

class TestEtatSanitaireApresChargement:
    """Tests du changement d'état sanitaire après chargement."""

    def test_propre_charge_propre_reste_propre(self, flux_blanchisserie_propre):
        etat = etat_sanitaire_apres_chargement(config.SANITAIRE_PROPRE, flux_blanchisserie_propre)
        assert etat == config.SANITAIRE_PROPRE

    def test_propre_charge_sale_devient_sale(self, flux_blanchisserie_sale):
        etat = etat_sanitaire_apres_chargement(config.SANITAIRE_PROPRE, flux_blanchisserie_sale)
        assert etat == config.SANITAIRE_SALE

    def test_sale_charge_propre_reste_sale(self, flux_blanchisserie_propre):
        """Même en chargeant du propre, un véhicule sale reste sale (besoin de désinfection)."""
        etat = etat_sanitaire_apres_chargement(config.SANITAIRE_SALE, flux_blanchisserie_propre)
        assert etat == config.SANITAIRE_SALE

    def test_sale_charge_sale_reste_sale(self, flux_blanchisserie_sale):
        etat = etat_sanitaire_apres_chargement(config.SANITAIRE_SALE, flux_blanchisserie_sale)
        assert etat == config.SANITAIRE_SALE


# ---------------------------------------------------------------------------
# get_vehicules_compatibles_flux
# ---------------------------------------------------------------------------

class TestGetVehiculesCompatiblesFlux:
    """Tests de récupération de la liste des véhicules compatibles avec un flux."""

    def test_plusieurs_vehicules_compatibles(
        self, vehicules_dict, sites_dict, flux_blanchisserie_propre
    ):
        """PL19T et PL12T devraient être compatibles avec ce flux (armoires de linge + quai)."""
        # PL12T a aussi "Armoires de linge": True dans les fixtures
        compat = get_vehicules_compatibles_flux(
            flux_blanchisserie_propre, vehicules_dict, sites_dict
        )
        assert "PL 19T" in compat

    def test_vl_seul_compatible_site_sans_quai(
        self, vehicules_dict, sites_dict, flux_pharmacie_mixte
    ):
        """Seuls les véhicules avec hayon sont compatibles pour un flux vers site sans quai."""
        compat = get_vehicules_compatibles_flux(
            flux_pharmacie_mixte, vehicules_dict, sites_dict
        )
        # PL19T et PL12T ne peuvent pas aller sur HGRL (sans quai)
        assert "PL 19T" not in compat
        assert "PL 12T" not in compat
        # VL et FOURGON (hayon=True) doivent être compatibles si le contenant l'est
        for vtype in compat:
            assert vehicules_dict[vtype].peut_operer_sans_quai

    def test_aucun_vehicule_compatible(self, vehicules_dict, sites_dict):
        """Flux avec contenant inconnu → aucun véhicule compatible."""
        from models import Flux
        flux = Flux(
            id_flux=999, site_depart="HSJ", site_arrivee="HLS",
            fonction_support="STERILISATION",
            type_contenant="CONTENANT_INEXISTANT",
            quantite=1,
            statut_plein_vide="Plein", statut_propre_sale="Propre",
            heure_dispo=360, heure_max_livraison=600,
        )
        compat = get_vehicules_compatibles_flux(flux, vehicules_dict, sites_dict)
        assert compat == []

    def test_retourne_liste_sans_doublons(
        self, vehicules_dict, sites_dict, flux_blanchisserie_propre
    ):
        """Le résultat ne doit pas comporter de doublons."""
        compat = get_vehicules_compatibles_flux(
            flux_blanchisserie_propre, vehicules_dict, sites_dict
        )
        assert len(compat) == len(set(compat)), "La liste des véhicules compatibles contient des doublons"

    def test_retourne_uniquement_types_connus(
        self, vehicules_dict, sites_dict, flux_blanchisserie_propre
    ):
        """Chaque type retourné doit appartenir au dictionnaire de véhicules fourni."""
        compat = get_vehicules_compatibles_flux(
            flux_blanchisserie_propre, vehicules_dict, sites_dict
        )
        for vtype in compat:
            assert vtype in vehicules_dict
