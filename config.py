"""
config.py — Configuration centrale d'OptiFLUX.
Contient toutes les constantes métier, colonnes obligatoires et paramètres par défaut.
Aucune valeur en dur ne doit figurer dans les autres modules.
"""

# ---------------------------------------------------------------------------
# ONGLETS OBLIGATOIRES DU FICHIER EXCEL
# ---------------------------------------------------------------------------
REQUIRED_SHEETS = [
    "param RH",
    "param Sites",
    "param Véhicules",
    "param Contenants",
    "matrice Durée",
    "matrice Dist",
    "LISTES",
    "M flux",
]

# ---------------------------------------------------------------------------
# COLONNES OBLIGATOIRES PAR ONGLET
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "param RH": ["Format horaire", "Pause", "heure début mini", "heure fin max"],
    "param Sites": ["Libellé", "Adresses", "Présence de quai"],
    "param Véhicules": [
        "Types",
        "Stationnement initial",
        "dim longueur interne (m)",
        "dim largeur interne (m)",
        "dim hauteur interne (m)",
        "Poids max chargement",
        "Consommation (L/km)",
        "Cout carburant (€/km)",
        "Cout carbone (kg/km)",
        "Présence hayon",
        "Temps de mise à quai - manœuvre, contact/admin (minutes)",
        "Manutention sans quai (minutes / contenants)",
        "Manutention avec quai (minutes / contenants)",
    ],
    "param Contenants": [
        "libellé",
        "dim longueur (m)",
        "dim largeur (m)",
        "Poids vide (T)",
        "Poids plein (T)",
    ],
    "M flux": [
        "Point de départ",
        "Point de destination",
        "Fonction Support associée",
        "Nature de contenant",
        "Plein / vide",
        "Sale / propre",
        "Transport mixte possible (OUI / NON)",
        "Nature du flux (les tournées sont elles à prévoir avec une obligation de transport ou une obligation de passage?)",
        "Quantité Lundi",
        "Quantité Mardi",
        "Quantité Mercredi",
        "Quantité Jeudi",
        "Quantité Vendredi",
        "Quantité Samedi",
        "Quantité Dimanche",
        "Heure de mise à disposition min départ",
        "Heure max de livraison à la destination",
    ],
}

# ---------------------------------------------------------------------------
# COLONNES DES QUANTITÉS (jours de la semaine)
# ---------------------------------------------------------------------------
DAY_COLUMNS = {
    0: "Quantité Lundi",
    1: "Quantité Mardi",
    2: "Quantité Mercredi",
    3: "Quantité Jeudi",
    4: "Quantité Vendredi",
    5: "Quantité Samedi",
    6: "Quantité Dimanche",
}

DAY_NAMES = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche",
}

WEEKEND_DAYS = {5, 6}  # Samedi, Dimanche

# ---------------------------------------------------------------------------
# PARAMÈTRES RH PAR DÉFAUT (en minutes depuis minuit)
# ---------------------------------------------------------------------------
DEFAULT_RH = {
    "vacation_duration": 450,
    "pause_duration": 30,
    "start_min": 390,
    "end_max": 1260,
}

# ---------------------------------------------------------------------------
# PARAMÈTRES OPÉRATIONNELS FIXES
# ---------------------------------------------------------------------------
PRISE_DE_POSTE_MIN = 15
FIN_DE_POSTE_MIN = 10
DESINFECTION_DURATION = 15
OPTIMIZATION_BUDGET_SEC = 120
PAUSE_WINDOW_HOURS = 60
LOOK_FORWARD_MIN = 30

# ---------------------------------------------------------------------------
# CAPACITÉS DES QUAIS PAR DÉFAUT
# ---------------------------------------------------------------------------
DEFAULT_DOCK_CAPACITY = 3
SITE_DOCK_OVERRIDES = {
    "HSJ": 2,
    "HLS": 6,
}
HSJ_SUBDOCK_SITES_PREFIX = "HSJ_"
HSJ_SUBDOCK_CAPACITY = 1

# ---------------------------------------------------------------------------
# STATUTS SANITAIRES
# ---------------------------------------------------------------------------
SANITAIRE_PROPRE = "Propre"
SANITAIRE_SALE = "Sale"
STATUT_PLEIN = "Plein"
STATUT_VIDE = "Vide"

# ---------------------------------------------------------------------------
# NATURE DES FLUX
# ---------------------------------------------------------------------------
FLUX_VOLUME = "Volume"
FLUX_FREQUENCES = "Fréquences"

# ---------------------------------------------------------------------------
# TYPES D'OPÉRATIONS
# ---------------------------------------------------------------------------
OP_PRISE_POSTE = "Prise de poste"
OP_FIN_POSTE = "Fin de poste"
OP_TRAJET_VIDE = "Trajet à vide"
OP_TRAJET_CHARGE = "Trajet chargé"
OP_CHARGEMENT = "Chargement"
OP_DECHARGEMENT = "Déchargement"
OP_MISE_A_QUAI = "Mise à quai"
OP_PAUSE = "Pause"
OP_DESINFECTION = "Désinfection"
OP_ATTENTE = "Attente"
OP_INOCCUPE = "Temps inoccupé"

# ---------------------------------------------------------------------------
# COULEURS GANTT
# ---------------------------------------------------------------------------
GANTT_COLORS = {
    OP_PRISE_POSTE:   "#4CAF50",
    OP_FIN_POSTE:     "#4CAF50",
    OP_TRAJET_VIDE:   "#90CAF9",
    OP_TRAJET_CHARGE: "#1565C0",
    OP_CHARGEMENT:    "#FFA726",
    OP_DECHARGEMENT:  "#EF6C00",
    OP_MISE_A_QUAI:   "#CE93D8",
    OP_PAUSE:         "#FFEB3B",
    OP_DESINFECTION:  "#F44336",
    OP_ATTENTE:       "#B0BEC5",
    OP_INOCCUPE:      "#ECEFF1",
}

# ---------------------------------------------------------------------------
# LIMITES ET TOLÉRANCES
# ---------------------------------------------------------------------------
MIN_QUANTITY = 0
MAX_VEHICLES_MULTIPLIER = 1.5
CIRCULATION_FACTOR_DEFAULT = 0

# ---------------------------------------------------------------------------
# EXPORT EXCEL — NOMS D'ONGLETS
# ---------------------------------------------------------------------------
EXPORT_SHEETS = {
    "synthese_flotte":     "Synthèse flotte",
    "synthese_chauffeurs": "Synthèse chauffeurs",
    "tournees_vehicules":  "Tournées véhicules",
    "planning_chauffeurs": "Planning chauffeurs",
    "planning_quais":      "Planning quais",
    "flux_transportes":    "Flux transportés",
    "flux_non_servis":     "Flux non servis",
    "controles":           "Contrôles contraintes",
    "indicateurs":         "Indicateurs",
}
