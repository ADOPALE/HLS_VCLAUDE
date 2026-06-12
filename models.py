"""
models.py — Modèles de données métier OptiFLUX (Pydantic v2).

Définit les structures de données pour les sites, véhicules, contenants, flux
et postes chauffeurs. Chaque modèle est accompagné d'une docstring explicite.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class Site(BaseModel):
    """Représente un site logistique du groupement hospitalier."""
    libelle: str = Field(..., description="Identifiant exact du site (clé dans les matrices)")
    adresse: str = Field(default="", description="Adresse postale")
    presence_quai: bool = Field(..., description="Présence d'un quai de chargement/déchargement")
    capacite_quai: int = Field(default=3, description="Nombre de véhicules simultanés autorisés au quai")
    compat_vehicules: Dict[str, bool] = Field(
        default_factory=dict,
        description="Compatibilité par type de véhicule {type_véhicule: True/False}"
    )


class Vehicule(BaseModel):
    """Représente un type de véhicule disponible dans la flotte."""
    type_vehicule: str = Field(..., description="Identifiant du type de véhicule")
    stationnement_initial: str = Field(..., description="Site de départ/retour obligatoire")
    longueur: float = Field(..., description="Longueur interne en mètres")
    largeur: float = Field(..., description="Largeur interne en mètres")
    hauteur: float = Field(..., description="Hauteur interne en mètres")
    surface_utile: float = Field(..., description="Surface utile de plancher = longueur × largeur (m²)")
    poids_max: float = Field(..., description="Poids maximal de chargement en tonnes")
    consommation: float = Field(..., description="Consommation en L/km")
    cout_carburant: float = Field(..., description="Coût carburant en €/km")
    cout_carbone: float = Field(..., description="Coût carbone en kg CO₂/km")
    hayon: bool = Field(..., description="Présence d'un hayon (True = hayon présent)")
    compat_contenants: Dict[str, bool] = Field(
        default_factory=dict,
        description="Compatibilité par type de contenant {libellé_contenant: True/False}"
    )
    temps_mise_quai: int = Field(..., description="Temps de mise à quai en minutes")
    manu_sans_quai: Optional[int] = Field(
        None,
        description="Temps de manutention sans quai (min/contenant). None = NC (incompatible sites sans quai)"
    )
    manu_avec_quai: int = Field(..., description="Temps de manutention avec quai (min/contenant)")
    max_exemplaires: Optional[int] = Field(None, description="Nombre max d'exemplaires autorisés (None = illimité)")
    actif: bool = Field(default=True, description="Type activé pour la simulation")

    @property
    def peut_operer_sans_quai(self) -> bool:
        """True si le véhicule peut opérer sur un site sans quai."""
        return self.hayon and (self.manu_sans_quai is not None)


class Contenant(BaseModel):
    """Représente un type de contenant logistique."""
    libelle: str = Field(..., description="Identifiant exact du contenant")
    longueur: float = Field(..., description="Longueur en mètres")
    largeur: float = Field(..., description="Largeur en mètres")
    poids_vide: float = Field(..., description="Poids vide en tonnes")
    poids_plein: float = Field(..., description="Poids plein en tonnes")

    @property
    def surface(self) -> float:
        """Surface d'emprise du contenant en m²."""
        return self.longueur * self.largeur


class Flux(BaseModel):
    """Représente un flux logistique à transporter."""
    id_flux: int = Field(..., description="Identifiant de ligne Excel (index 1-based depuis header)")
    site_depart: str = Field(..., description="Site de collecte")
    site_arrivee: str = Field(..., description="Site de livraison")
    fonction_support: str = Field(..., description="Fonction support (BLANCHISSERIE, MAGASIN, etc.)")
    nature_flux: str = Field(default="", description="Description libre du flux")
    type_contenant: str = Field(..., description="Libellé du contenant")
    quantite: int = Field(..., description="Nombre de contenants pour le jour simulé")
    statut_plein_vide: str = Field(..., description="'Plein' ou 'Vide'")
    statut_propre_sale: str = Field(..., description="'Propre' ou 'Sale'")
    aller_retour: str = Field(default="", description="'Aller' ou 'Retour'")
    transport_mixte: bool = Field(default=False, description="Transport mixte propre/sale autorisé")
    regle_exclusion: Optional[str] = Field(
        None,
        description="Statut sanitaire interdit en chargement mixte ('Sale' ou 'Propre')"
    )
    tournee_mutualisee: bool = Field(default=False, description="Flux appartenant à une tournée mutualisée")
    nom_tournee: Optional[str] = Field(None, description="Nom de la tournée mutualisée")
    heure_dispo: int = Field(..., description="Heure de mise à disposition min départ (minutes depuis minuit)")
    heure_max_livraison: int = Field(..., description="Heure max de livraison à la destination (minutes)")
    urgent: bool = Field(default=False, description="Flux prioritaire/urgent")
    # Calculés
    volume_total: float = Field(default=0.0, description="Volume calculé (m² × quantité)")
    poids_total: float = Field(default=0.0, description="Poids total (tonnes)")


class StepOperation(BaseModel):
    """Une étape dans la séquence chronologique d'un poste chauffeur."""
    heure_debut: int = Field(..., description="Heure de début (minutes depuis minuit)")
    heure_fin: int = Field(..., description="Heure de fin (minutes depuis minuit)")
    type_operation: str = Field(..., description="Type d'opération (trajet, chargement, etc.)")
    site: str = Field(default="", description="Site concerné")
    flux_ids: List[int] = Field(default_factory=list, description="IDs des flux concernés")
    nb_contenants: int = Field(default=0, description="Nombre de contenants chargés/déchargés")
    type_contenant: str = Field(default="", description="Type de contenant")
    taux_remplissage_surface: float = Field(default=0.0, description="Taux de remplissage surfacique [0-1]")
    taux_remplissage_poids: float = Field(default=0.0, description="Taux de remplissage poids [0-1]")
    statut_sanitaire: str = Field(default="Propre", description="État sanitaire du véhicule après cette étape")
    distance_km: float = Field(default=0.0, description="Distance en km (pour trajets)")
    est_trajet_vide: bool = Field(default=False, description="True si le véhicule est à vide")
    commentaire: str = Field(default="", description="Commentaire libre")


class Tournee(BaseModel):
    """Une tournée regroupant un ou plusieurs flux sur un véhicule."""
    id_tournee: int = Field(..., description="Identifiant unique de la tournée")
    type_vehicule: str = Field(..., description="Type de véhicule affecté")
    flux_ids: List[int] = Field(default_factory=list, description="IDs des flux inclus")
    sequence_sites: List[str] = Field(default_factory=list, description="Séquence des sites visités")
    steps: List[StepOperation] = Field(default_factory=list, description="Séquence détaillée des opérations")
    heure_debut: int = Field(default=0, description="Heure de début de la tournée")
    heure_fin: int = Field(default=0, description="Heure de fin de la tournée")
    km_total: float = Field(default=0.0, description="Kilométrage total")
    km_vide: float = Field(default=0.0, description="Kilométrage à vide")
    nb_desinfections: int = Field(default=0, description="Nombre de désinfections")


class PosteChaufeur(BaseModel):
    """Un poste de travail d'un chauffeur sur un véhicule."""
    id_poste: int = Field(..., description="Identifiant unique du poste")
    numero_poste: int = Field(..., description="Numéro séquentiel du poste sur le véhicule (1 ou 2)")
    type_vehicule: str = Field(..., description="Type de véhicule")
    heure_debut: int = Field(..., description="Heure de début du poste")
    heure_fin: int = Field(..., description="Heure de fin du poste")
    duree_vacation: int = Field(..., description="Durée exacte du poste (= durée de vacation RH)")
    tournees: List[int] = Field(default_factory=list, description="IDs des tournées du poste")
    steps: List[StepOperation] = Field(default_factory=list, description="Séquence détaillée du poste")
    temps_prise_poste: int = Field(default=15)
    temps_fin_poste: int = Field(default=10)
    temps_pause: int = Field(default=30)
    temps_conduite: int = Field(default=0)
    temps_manutention: int = Field(default=0)
    temps_quai: int = Field(default=0)
    temps_desinfection: int = Field(default=0)
    temps_attente: int = Field(default=0)
    temps_inoccupe: int = Field(default=0)
    nb_desinfections: int = Field(default=0)


class ResultatJour(BaseModel):
    """Résultat complet de simulation pour un jour donné."""
    jour: str = Field(..., description="Nom du jour (Lundi, Mardi, ...)")
    jour_idx: int = Field(..., description="Index du jour (0=Lundi, 6=Dimanche)")
    tournees: List[Tournee] = Field(default_factory=list)
    postes: List[PosteChaufeur] = Field(default_factory=list)
    flux_transportes: List[int] = Field(default_factory=list, description="IDs flux servis")
    flux_non_servis: List[Dict[str, Any]] = Field(default_factory=list, description="Flux non servis avec raison")
    nb_vehicules: int = Field(default=0)
    nb_postes: int = Field(default=0)
    km_total: float = Field(default=0.0)
    km_vide: float = Field(default=0.0)
    nb_desinfections: int = Field(default=0)
    taux_service: float = Field(default=0.0, description="% flux servis")
    erreurs_conformite: List[Dict[str, Any]] = Field(default_factory=list)
