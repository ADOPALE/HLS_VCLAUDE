"""
conftest.py — Fixtures pytest partagées pour les tests OptiFLUX.
"""
import sys
import os

# Ajouter le répertoire parent au sys.path pour que les imports de modules fonctionnent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from models import Site, Vehicule, Contenant, Flux


# ---------------------------------------------------------------------------
# FIXTURES SITES
# ---------------------------------------------------------------------------

@pytest.fixture
def site_avec_quai():
    """Site standard avec quai, compatible PL et VL."""
    return Site(
        libelle="HSJ",
        adresse="CHU Nantes - Saint-Jacques",
        presence_quai=True,
        capacite_quai=2,
        compat_vehicules={"PL 12T": True, "PL 19T": True, "VL (UTILITAIRE)": True, "FOURGON": True},
    )


@pytest.fixture
def site_sans_quai():
    """Site satellite sans quai, accessible uniquement par VL avec hayon."""
    return Site(
        libelle="HGRL",
        adresse="Hôpital G. R. Laënnec",
        presence_quai=False,
        capacite_quai=0,
        compat_vehicules={"VL (UTILITAIRE)": True, "FOURGON": True, "PL 12T": False, "PL 19T": False},
    )


@pytest.fixture
def site_hsj():
    """Site HSJ - stationnement principal."""
    return Site(
        libelle="HSJ",
        adresse="Hôpital Saint-Jacques",
        presence_quai=True,
        capacite_quai=2,
        compat_vehicules={"PL 12T": True, "PL 19T": True, "VL (UTILITAIRE)": True, "FOURGON": True},
    )


@pytest.fixture
def site_hls():
    """Site HLS - grand site avec quai."""
    return Site(
        libelle="HLS",
        adresse="Hôpital Laënnec Substitut",
        presence_quai=True,
        capacite_quai=6,
        compat_vehicules={"PL 12T": True, "PL 19T": True, "VL (UTILITAIRE)": True, "FOURGON": True},
    )


# ---------------------------------------------------------------------------
# FIXTURES VÉHICULES
# ---------------------------------------------------------------------------

@pytest.fixture
def vehicule_pl19t():
    """PL 19T — grand porteur, sans hayon, incompatible sites sans quai."""
    return Vehicule(
        type_vehicule="PL 19T",
        stationnement_initial="HSJ",
        longueur=7.5,
        largeur=2.4,
        hauteur=2.5,
        surface_utile=18.0,
        poids_max=12.0,
        consommation=28.0,
        cout_carburant=0.42,
        cout_carbone=0.074,
        hayon=False,
        compat_contenants={
            "Armoires de linge": True,
            "Rolls linge sale": True,
            "Rolls PUI_MG": True,
            "Palette": True,
            "Petit contenant/colis": True,
        },
        temps_mise_quai=5,
        manu_sans_quai=None,   # NC — ne peut pas opérer sans quai
        manu_avec_quai=2,
        max_exemplaires=None,
        actif=True,
    )


@pytest.fixture
def vehicule_pl12t():
    """PL 12T — porteur standard, sans hayon."""
    return Vehicule(
        type_vehicule="PL 12T",
        stationnement_initial="HSJ",
        longueur=6.0,
        largeur=2.4,
        hauteur=2.5,
        surface_utile=14.4,
        poids_max=7.0,
        consommation=22.0,
        cout_carburant=0.33,
        cout_carbone=0.058,
        hayon=False,
        compat_contenants={
            "Armoires de linge": True,
            "Rolls linge sale": True,
            "Palette": True,
            "Petit contenant/colis": True,
        },
        temps_mise_quai=5,
        manu_sans_quai=None,
        manu_avec_quai=2,
        max_exemplaires=None,
        actif=True,
    )


@pytest.fixture
def vehicule_vl():
    """VL Utilitaire — petit véhicule avec hayon, compatible sites sans quai."""
    return Vehicule(
        type_vehicule="VL (UTILITAIRE)",
        stationnement_initial="HSJ",
        longueur=3.0,
        largeur=1.8,
        hauteur=1.8,
        surface_utile=5.4,
        poids_max=1.5,
        consommation=10.0,
        cout_carburant=0.15,
        cout_carbone=0.026,
        hayon=True,
        compat_contenants={
            "Petit contenant/colis": True,
            "Caisses vertes blanchisserie": True,
            "Rolls PUI_MG": False,
        },
        temps_mise_quai=3,
        manu_sans_quai=5,
        manu_avec_quai=3,
        max_exemplaires=2,
        actif=True,
    )


@pytest.fixture
def vehicule_fourgon():
    """Fourgon — avec hayon, compatible sites sans quai."""
    return Vehicule(
        type_vehicule="FOURGON",
        stationnement_initial="HSJ",
        longueur=4.0,
        largeur=2.0,
        hauteur=2.0,
        surface_utile=8.0,
        poids_max=2.5,
        consommation=12.0,
        cout_carburant=0.18,
        cout_carbone=0.031,
        hayon=True,
        compat_contenants={
            "Petit contenant/colis": True,
            "Caisses vertes blanchisserie": True,
            "Rolls PUI_MG": True,
            "Armoires de linge": False,
        },
        temps_mise_quai=3,
        manu_sans_quai=4,
        manu_avec_quai=2,
        max_exemplaires=None,
        actif=True,
    )


# ---------------------------------------------------------------------------
# FIXTURES CONTENANTS
# ---------------------------------------------------------------------------

@pytest.fixture
def contenant_roll():
    """Roll de linge sale — grand format."""
    return Contenant(
        libelle="Rolls linge sale",
        longueur=0.8,
        largeur=0.6,
        poids_vide=0.025,
        poids_plein=0.080,
    )


@pytest.fixture
def contenant_armoire():
    """Armoire de linge — très grand format."""
    return Contenant(
        libelle="Armoires de linge",
        longueur=1.2,
        largeur=0.6,
        poids_vide=0.040,
        poids_plein=0.120,
    )


@pytest.fixture
def contenant_petit():
    """Petit contenant/colis — petit format."""
    return Contenant(
        libelle="Petit contenant/colis",
        longueur=0.4,
        largeur=0.3,
        poids_vide=0.005,
        poids_plein=0.020,
    )


# ---------------------------------------------------------------------------
# FIXTURES FLUX
# ---------------------------------------------------------------------------

@pytest.fixture
def flux_blanchisserie_propre(site_avec_quai, site_hls):
    """Flux de linge propre HSJ → HLS."""
    return Flux(
        id_flux=1,
        site_depart="HSJ",
        site_arrivee="HLS",
        fonction_support="BLANCHISSERIE",
        nature_flux="Volume",
        type_contenant="Armoires de linge",
        quantite=10,
        statut_plein_vide="Plein",
        statut_propre_sale="Propre",
        aller_retour="Aller",
        transport_mixte=False,
        regle_exclusion=None,
        tournee_mutualisee=False,
        nom_tournee=None,
        heure_dispo=360,         # 06:00
        heure_max_livraison=480, # 08:00
        urgent=False,
        volume_total=7.2,
        poids_total=1.2,
    )


@pytest.fixture
def flux_blanchisserie_sale(site_hls, site_avec_quai):
    """Flux de linge sale HLS → HSJ."""
    return Flux(
        id_flux=2,
        site_depart="HLS",
        site_arrivee="HSJ",
        fonction_support="BLANCHISSERIE",
        nature_flux="Volume",
        type_contenant="Rolls linge sale",
        quantite=8,
        statut_plein_vide="Plein",
        statut_propre_sale="Sale",
        aller_retour="Retour",
        transport_mixte=False,
        regle_exclusion=None,
        tournee_mutualisee=False,
        nom_tournee=None,
        heure_dispo=420,          # 07:00
        heure_max_livraison=600,  # 10:00
        urgent=False,
        volume_total=3.84,
        poids_total=0.64,
    )


@pytest.fixture
def flux_pharmacie_mixte():
    """Flux pharmacie autorisant le transport mixte."""
    return Flux(
        id_flux=3,
        site_depart="HSJ",
        site_arrivee="HGRL",
        fonction_support="PHARMACIE",
        nature_flux="Volume",
        type_contenant="Petit contenant/colis",
        quantite=5,
        statut_plein_vide="Plein",
        statut_propre_sale="Propre",
        aller_retour="Aller",
        transport_mixte=True,
        regle_exclusion="Sale",
        tournee_mutualisee=False,
        nom_tournee=None,
        heure_dispo=480,          # 08:00
        heure_max_livraison=660,  # 11:00
        urgent=False,
        volume_total=0.6,
        poids_total=0.1,
    )


# ---------------------------------------------------------------------------
# FIXTURES MATRICES
# ---------------------------------------------------------------------------

@pytest.fixture
def matrix_dur():
    """Matrice de durées minimale (en minutes) entre sites de test."""
    return {
        "HSJ":  {"HSJ": 0,  "HLS": 25, "HGRL": 30},
        "HLS":  {"HSJ": 25, "HLS": 0,  "HGRL": 40},
        "HGRL": {"HSJ": 30, "HLS": 40, "HGRL": 0},
    }


@pytest.fixture
def matrix_dist():
    """Matrice de distances minimale (en km) entre sites de test."""
    return {
        "HSJ":  {"HSJ": 0,   "HLS": 18.0, "HGRL": 22.0},
        "HLS":  {"HSJ": 18.0, "HLS": 0,   "HGRL": 30.0},
        "HGRL": {"HSJ": 22.0, "HLS": 30.0, "HGRL": 0},
    }


@pytest.fixture
def sites_dict(site_avec_quai, site_hls, site_sans_quai):
    """Dictionnaire de sites pour les tests."""
    return {
        "HSJ":  site_avec_quai,
        "HLS":  site_hls,
        "HGRL": site_sans_quai,
    }


@pytest.fixture
def vehicules_dict(vehicule_pl19t, vehicule_pl12t, vehicule_vl, vehicule_fourgon):
    """Dictionnaire de véhicules pour les tests."""
    return {
        "PL 19T":         vehicule_pl19t,
        "PL 12T":         vehicule_pl12t,
        "VL (UTILITAIRE)": vehicule_vl,
        "FOURGON":         vehicule_fourgon,
    }
