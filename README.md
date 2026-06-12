# OptiFLUX — Optimisation Logistique Hospitalière

Application Streamlit d'optimisation des tournées logistiques multi-flux pour groupements hospitaliers. Elle prend en charge les flux de linge, repas, médicaments et dispositifs médicaux stériles, et produit un planning quotidien de tournées véhicules, postes chauffeurs et occupation des quais.

---

## Fonctionnalités

- **Import Excel paramétré** — lecture du fichier de paramètres standardisé (sites, véhicules, contenants, matrices de durée/distance, flux)
- **Contrôles de cohérence** — vérifications bloquantes et alertes avant simulation
- **Simulation multi-jours** — de Lundi à Dimanche, avec quantités variables par flux et par jour
- **Optimisation Clarke-Wright + 2-opt** — construction et amélioration des tournées en 2 minutes de budget CPU
- **Gestion des contraintes métier** complètes :
  - Fenêtres horaires strictes (T_min vérifié avant optimisation)
  - Capacité 2D surfacique + contrainte de poids
  - Compatibilité véhicule / site / contenant
  - Règles propre/sale et transport mixte
  - Désinfection 15 min obligatoire au retour au stationnement
  - Postes chauffeurs calés exactement sur la durée de vacation RH
  - Pause obligatoire dans la fenêtre ±1 h autour du milieu du poste
  - Gestion des conflits de quai
- **Visualisation Gantt** interactive (Plotly) par véhicule et par chauffeur
- **Export Excel** 9 onglets (synthèse flotte, chauffeurs, tournées, planning quais, indicateurs…)

---

## Structure du projet

```
optiflux/
├── app.py                  # Interface Streamlit principale (5 onglets)
├── config.py               # Constantes et paramètres par défaut
├── models.py               # Modèles de données Pydantic v2
├── data_loader.py          # Import et parsing du fichier Excel
├── validators.py           # Contrôles de cohérence pré-simulation
├── preprocessing.py        # Filtrage et préparation des flux actifs
├── capacity.py             # Calcul de capacité surfacique 2D + poids
├── compatibility.py        # Règles de compatibilité véhicule/site/flux
├── time_windows.py         # Calcul T_min et détection flux infaisables
├── optimizer.py            # Clarke-Wright Savings + 2-opt inter-tournées
├── route_builder.py        # Construction de la séquence chronologique
├── driver_scheduler.py     # Affectation des postes chauffeurs
├── dock_scheduler.py       # Planning et résolution des conflits de quai
├── visualization.py        # Diagrammes Gantt Plotly
├── fleet_generator.py      # Générateur de flotte (exemplaires de véhicules)
├── outputs.py              # Export Excel xlsxwriter
├── requirements.txt
├── .gitignore
└── tests/
    ├── conftest.py          # Fixtures pytest partagées
    ├── test_import.py       # Tests d'import et d'instanciation
    ├── test_capacity.py     # Tests de capacité surfacique et poids
    ├── test_compatibility.py # Tests de compatibilité véhicule/flux
    ├── test_time_windows.py # Tests de fenêtres horaires et T_min
    └── test_rh.py           # Tests de validation des paramètres RH
```

---

## Installation

```bash
# Cloner le dépôt
git clone <url-du-depot>
cd optiflux

# Créer un environnement virtuel (recommandé)
python -m venv .venv
source .venv/bin/activate       # Linux / macOS
# ou
.venv\Scripts\activate          # Windows

# Installer les dépendances
pip install -r requirements.txt
```

Prérequis : **Python 3.11+**

---

## Démarrage

```bash
streamlit run app.py
```

L'application s'ouvre dans le navigateur sur `http://localhost:8501`.

---

## Utilisation

### 1. Import & Contrôles

Glissez-déposez le fichier `OptiFLUX_Parametres_AAAMMJJ.xlsx` dans l'onglet **Import & Contrôles**. L'application vérifie automatiquement :

- Présence des 8 onglets obligatoires
- Colonnes obligatoires par onglet
- Cohérence RH (pause < vacation, plage horaire suffisante)
- Matrices carrées et alignées sur les mêmes sites
- Stationnements initiaux valides
- Références sites/contenants dans les flux

Les **erreurs bloquantes** empêchent le lancement de la simulation. Les **alertes** sont affichées mais n'empêchent pas l'exécution.

### 2. Paramètres

Ajustez les paramètres RH (durée de vacation, pause, plage horaire) et le facteur de circulation avant de lancer la simulation.

### 3. Simulation

Sélectionnez le ou les jours à simuler. La simulation lance l'algorithme Clarke-Wright avec amélioration 2-opt dans un budget de 2 minutes par jour. Les flux non servis sont listés avec leur motif d'exclusion.

### 4. Résultats

Visualisation des Gantt de tournées (par véhicule) et de postes (par chauffeur). Navigation jour par jour.

### 5. Export

Téléchargement du fichier `OptiFLUX_Resultats.xlsx` avec 9 onglets de résultats détaillés.

---

## Format du fichier Excel de paramètres

Le fichier doit comporter **8 onglets** :

| Onglet | Contenu |
|--------|---------|
| `param RH` | Durée de vacation, pause, plages horaires |
| `param Sites` | Liste des sites, adresses, présence de quai |
| `param Véhicules` | Types de véhicules, dimensions, coûts, compatibilités |
| `param Contenants` | Types de contenants, dimensions, poids |
| `matrice Durée` | Matrice carrée des durées de trajet (min) |
| `matrice Dist` | Matrice carrée des distances (km) |
| `LISTES` | Listes de référence (fonctions support, statuts…) |
| `M flux` | Flux logistiques : sites, contenants, quantités par jour, horaires |

> ⚠️ Les formules Excel doivent être **calculées** avant export (Ctrl+Shift+F9 sous Excel Windows). Les cellules contenant des formules non évaluées génèrent une erreur bloquante.

### Flux ignorés

Les lignes de l'onglet `M flux` dont la colonne **Nature du flux** est `Fréquences` sont ignorées. Seuls les flux de nature `Volume` avec quantité > 0 pour le jour simulé sont traités.

---

## Contraintes métier clés

### Désinfection

La désinfection (15 min) est obligatoire au **stationnement initial** après toute tournée impliquant du linge sale ou tout flux marqué `Sale`. Elle est comptée dans le poste chauffeur.

### Pause réglementaire

La pause est positionnée dans la fenêtre de ±60 min autour du milieu théorique du poste, uniquement lorsque le véhicule est au stationnement initial.

### Prise / fin de poste

- Prise de poste : 15 min incompressibles en début de poste
- Fin de poste : 10 min incompressibles en fin de poste

### Sites sans quai

Un véhicule sans hayon, ou avec `Manutention sans quai = NC`, ne peut pas desservir un site sans quai. La colonne `Manutention sans quai (minutes / contenants)` = `NC` dans le fichier Excel est interprétée comme `None` et rend le véhicule incompatible.

---

## Tests

```bash
# Lancer tous les tests
pytest tests/ -v

# Avec rapport de couverture
pytest tests/ -v --cov=. --cov-report=html
```

Les tests couvrent les modules `capacity`, `compatibility`, `time_windows`, `validators` (RH), et les imports/modèles. Ils n'ont pas besoin du fichier Excel source.

---

## Architecture de l'algorithme d'optimisation

1. **Prétraitement** — filtrage des flux actifs (Volume, quantité > 0, jour simulé)
2. **Détection des flux infaisables** — T_min calculé pour chaque flux avec le véhicule le plus favorable ; flux infaisables signalés
3. **Construction initiale** — chaque flux est affecté à une tournée individuelle (solution initiale)
4. **Clarke-Wright Savings** — fusion itérative des tournées selon les économies de distance
5. **2-opt inter-tournées** — réallocation de flux entre tournées pour réduire le kilométrage total
6. **Budget temps** — 120 secondes par jour ; la meilleure solution dans le budget est retenue
7. **Construction des routes** — séquence chronologique complète avec toutes les opérations
8. **Affectation des postes** — regroupement des tournées en postes de durée exacte = vacation RH

---

## Licence

Usage interne — groupement hospitalier universitaire. Non distribué publiquement.
