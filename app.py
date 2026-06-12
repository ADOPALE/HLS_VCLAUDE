"""
app.py — Interface Streamlit OptiFLUX.
Point d'entrée de l'application d'optimisation logistique hospitalière.

Lancement : streamlit run app.py
"""

from __future__ import annotations
import logging
import sys
import os

# Ajouter le répertoire courant au path
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd

import config
from data_loader import load_all
from validators import validate_all
from preprocessing import get_active_flux, get_tournees_mutualisees, get_fonctions_support
from time_windows import detecter_flux_infaisables, appliquer_facteur_circulation, minutes_to_hhmm
from models import Site, Vehicule, Contenant, Flux, Tournee, PosteChaufeur, ResultatJour
from optimizer import optimizer_run, construire_tournees_finales
from driver_scheduler import affecter_postes
from dock_scheduler import build_dock_planning, detecter_conflits_quai
from visualization import make_gantt_postes, make_timeline_poste, make_synthese_chart
from outputs import generate_excel_results

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION PAGE
# ============================================================================
st.set_page_config(
    page_title="OptiFLUX — Optimisation Logistique Hospitalière",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================================
# STYLES CSS
# ============================================================================
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1565C0, #0D47A1);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 12px rgba(21,101,192,0.3);
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
    .main-header p { color: #BBDEFB; margin: 0.3rem 0 0 0; font-size: 0.95rem; }
    .metric-card {
        background: white;
        border: 1px solid #E3F2FD;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        text-align: center;
    }
    .metric-card .value { font-size: 2rem; font-weight: bold; color: #1565C0; }
    .metric-card .label { font-size: 0.85rem; color: #666; margin-top: 0.2rem; }
    .status-ok { color: #2E7D32; font-weight: bold; }
    .status-error { color: #C62828; font-weight: bold; }
    .status-warning { color: #E65100; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1.2rem;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# EN-TÊTE
# ============================================================================
st.markdown("""
<div class="main-header">
    <h1>🏥 OptiFLUX</h1>
    <p>Optimisation logistique hospitalière multi-flux — Planification des tournées véhicules</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE
# ============================================================================
def init_session():
    defaults = {
        "data_loaded": False,
        "raw_data": None,
        "import_errors": [],
        "import_warnings": [],
        "formulas": [],
        "sites_models": {},
        "vehicules_models": {},
        "contenants_models": {},
        "rh_params": config.DEFAULT_RH.copy(),
        "dock_capacities": {},
        "circulation_factor": 0,
        "max_vehicules": {},
        "vehicules_actifs": {},
        "resultats": [],
        "simulation_done": False,
        "flux_infaisables": [],
        "fonctions_disponibles": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# ============================================================================
# ONGLETS PRINCIPAUX
# ============================================================================
tab_icons = ["📥 Import & Contrôles", "⚙️ Paramètres", "▶️ Simulation", "📊 Résultats", "📤 Export"]
tabs = st.tabs(tab_icons)

# ============================================================================
# ONGLET 1 — IMPORT & CONTRÔLES
# ============================================================================
with tabs[0]:
    st.subheader("Chargement du fichier de paramétrage")
    st.info(
        "Chargez votre fichier Excel OptiFLUX (.xlsx) contenant les onglets : "
        "`param RH`, `param Sites`, `param Véhicules`, `param Contenants`, "
        "`matrice Durée`, `matrice Dist`, `LISTES`, `M flux`.",
        icon="ℹ️"
    )

    uploaded_file = st.file_uploader(
        "Sélectionner le fichier Excel",
        type=["xlsx"],
        help="Format attendu : fichier Excel OptiFLUX structuré selon les spécifications.",
        key="file_uploader",
    )

    if uploaded_file:
        with st.spinner("Lecture et contrôle du fichier en cours…"):
            try:
                # Sauvegarder temporairement
                import tempfile, os
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                raw = load_all(tmp_path)
                os.unlink(tmp_path)

                # Stocker dans la session
                st.session_state.raw_data = raw
                st.session_state.import_errors = raw.get("errors", [])
                st.session_state.import_warnings = raw.get("warnings", [])
                st.session_state.formulas = raw.get("formulas", [])

                # Validation de cohérence
                if not raw.get("errors"):
                    val_result = validate_all(
                        raw["rh"], raw["sites"], raw["vehicules"], raw["contenants"],
                        raw["matrix_dur"], raw["matrix_dist"], raw["flux_brut"]
                    )
                    st.session_state.import_errors += val_result["errors"]
                    st.session_state.import_warnings += val_result["warnings"]

                if not st.session_state.import_errors:
                    # Construire les modèles
                    _build_models(raw)
                    st.session_state.data_loaded = True
                    st.session_state.fonctions_disponibles = get_fonctions_support(raw["flux_brut"])

            except Exception as e:
                st.error(f"Erreur lors du chargement : {e}")
                logger.exception("Erreur chargement fichier")

    # Rapport d'import
    if st.session_state.raw_data:
        raw = st.session_state.raw_data
        st.markdown("---")
        st.subheader("Rapport d'import")

        # Métriques
        if not raw.get("errors"):
            c1, c2, c3, c4, c5 = st.columns(5)
            nb_sites = len(raw.get("sites", {}))
            nb_veh = len(raw.get("vehicules", {}))
            nb_cont = len(raw.get("contenants", {}))
            nb_flux = len([f for f in raw.get("flux_brut", [])
                           if f.get("nature", "").strip() == "Volume"])
            nb_fonctions = len(st.session_state.fonctions_disponibles)
            with c1:
                st.metric("Sites", nb_sites, help="Nombre de sites importés")
            with c2:
                st.metric("Types véhicules", nb_veh)
            with c3:
                st.metric("Contenants", nb_cont)
            with c4:
                st.metric("Flux Volume", nb_flux)
            with c5:
                st.metric("Fonctions support", nb_fonctions)

        # Erreurs bloquantes
        errors = st.session_state.import_errors
        if errors:
            st.error(f"⛔ {len(errors)} erreur(s) bloquante(s) — La simulation est bloquée.")
            for e in errors:
                with st.expander(f"❌ {e.get('type', 'ERREUR')} — {e.get('message', '')[:80]}"):
                    st.write(e)
        else:
            st.success("✅ Aucune erreur bloquante détectée.", icon="✅")

        # Alertes non bloquantes
        warnings = st.session_state.import_warnings
        if warnings:
            st.warning(f"⚠️ {len(warnings)} alerte(s) non bloquante(s).")
            for w in warnings[:10]:
                st.markdown(f"- {w.get('message', '')}")
            if len(warnings) > 10:
                st.caption(f"… et {len(warnings)-10} autre(s).")

        # Formules Excel
        formulas = st.session_state.formulas
        if formulas:
            st.error(f"⛔ {len(formulas)} cellule(s) de quantité contiennent des formules non calculées.")
            df_form = pd.DataFrame(formulas)
            st.dataframe(df_form, use_container_width=True)


def _build_models(raw: dict):
    """Construit les modèles Pydantic à partir des données brutes."""
    # Sites
    sites_models = {}
    for libelle, sdata in raw["sites"].items():
        cap = _get_dock_capacity(libelle)
        sites_models[libelle] = Site(
            libelle=libelle,
            adresse=sdata.get("adresse", ""),
            presence_quai=sdata.get("presence_quai", False),
            capacite_quai=cap,
            compat_vehicules=sdata.get("compat_vehicules", {}),
        )
    st.session_state.sites_models = sites_models

    # Véhicules
    veh_models = {}
    for vtype, vdata in raw["vehicules"].items():
        lon = vdata.get("longueur", 0)
        larg = vdata.get("largeur", 0)
        veh_models[vtype] = Vehicule(
            type_vehicule=vtype,
            stationnement_initial=vdata.get("stationnement_initial", "HSJ"),
            longueur=lon,
            largeur=larg,
            hauteur=vdata.get("hauteur", 0),
            surface_utile=lon * larg,
            poids_max=vdata.get("poids_max", 0),
            consommation=vdata.get("consommation", 0),
            cout_carburant=vdata.get("cout_carburant", 0),
            cout_carbone=vdata.get("cout_carbone", 0),
            hayon=vdata.get("hayon", False),
            compat_contenants=vdata.get("compat_contenants", {}),
            temps_mise_quai=vdata.get("temps_mise_quai", 10),
            manu_sans_quai=vdata.get("manu_sans_quai"),
            manu_avec_quai=vdata.get("manu_avec_quai", 1),
            actif=st.session_state.vehicules_actifs.get(vtype, True),
            max_exemplaires=st.session_state.max_vehicules.get(vtype),
        )
    st.session_state.vehicules_models = veh_models

    # Contenants
    cont_models = {}
    for lib, cdata in raw["contenants"].items():
        cont_models[lib] = Contenant(
            libelle=lib,
            longueur=cdata.get("longueur", 0),
            largeur=cdata.get("largeur", 0),
            poids_vide=cdata.get("poids_vide", 0),
            poids_plein=cdata.get("poids_plein", 0),
        )
    st.session_state.contenants_models = cont_models

    # RH
    if "rh" in raw:
        st.session_state.rh_params = raw["rh"]


def _get_dock_capacity(libelle: str) -> int:
    """Détermine la capacité de quai d'un site."""
    if libelle in st.session_state.dock_capacities:
        return st.session_state.dock_capacities[libelle]
    if libelle in config.SITE_DOCK_OVERRIDES:
        return config.SITE_DOCK_OVERRIDES[libelle]
    if libelle.startswith(config.HSJ_SUBDOCK_SITES_PREFIX):
        return config.HSJ_SUBDOCK_CAPACITY
    return config.DEFAULT_DOCK_CAPACITY


# ============================================================================
# ONGLET 2 — PARAMÈTRES
# ============================================================================
with tabs[1]:
    if not st.session_state.data_loaded:
        st.info("Veuillez d'abord charger un fichier valide dans l'onglet **Import & Contrôles**.")
    else:
        st.subheader("Paramètres de simulation")

        # --- RH ---
        with st.expander("⏰ Paramètres RH", expanded=True):
            rh = st.session_state.rh_params
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                vac = st.number_input(
                    "Durée de vacation (min)", min_value=60, max_value=720,
                    value=rh.get("vacation_duration", 450), step=15,
                    help="Durée exacte d'un poste chauffeur en minutes."
                )
            with c2:
                pause = st.number_input(
                    "Durée de pause (min)", min_value=0, max_value=120,
                    value=rh.get("pause_duration", 30), step=5
                )
            with c3:
                start_h = rh.get("start_min", 390) // 60
                start_m = rh.get("start_min", 390) % 60
                start_str = st.text_input("Heure début mini (HH:MM)", f"{start_h:02d}:{start_m:02d}")
            with c4:
                end_h = rh.get("end_max", 1260) // 60
                end_m = rh.get("end_max", 1260) % 60
                end_str = st.text_input("Heure fin max (HH:MM)", f"{end_h:02d}:{end_m:02d}")

            # Mise à jour
            try:
                start_parts = start_str.split(":")
                end_parts = end_str.split(":")
                start_min = int(start_parts[0]) * 60 + int(start_parts[1])
                end_max = int(end_parts[0]) * 60 + int(end_parts[1])
                st.session_state.rh_params = {
                    "vacation_duration": vac,
                    "pause_duration": pause,
                    "start_min": start_min,
                    "end_max": end_max,
                }
                # Contrôle temps réel
                if pause >= vac:
                    st.error("⚠️ La pause doit être inférieure à la vacation.")
                elif start_min + vac > end_max:
                    st.warning("⚠️ Heure début + vacation > heure fin max.")
                else:
                    st.success("✅ Paramètres RH cohérents.")
            except Exception:
                st.error("Format d'heure invalide — attendu HH:MM")

        # --- Réseau ---
        with st.expander("🚦 Facteur de circulation", expanded=False):
            circ = st.slider(
                "Facteur de circulation (%)",
                min_value=0, max_value=100,
                value=st.session_state.circulation_factor,
                step=5,
                help="Appliqué à toutes les durées de trajet. 0 = durées nominales."
            )
            st.session_state.circulation_factor = circ
            if circ > 0:
                st.info(f"Les durées de trajet seront multipliées par ×{1+circ/100:.2f}")

        # --- Flotte ---
        with st.expander("🚚 Paramètres flotte", expanded=False):
            st.markdown("Configurez le nombre maximal d'exemplaires et l'activation de chaque type de véhicule.")
            for vtype, veh in st.session_state.vehicules_models.items():
                c1, c2, c3 = st.columns([3, 2, 2])
                with c1:
                    st.markdown(f"**{vtype}** — {veh.longueur}×{veh.largeur}m, {veh.poids_max}T")
                with c2:
                    actif = st.checkbox(f"Actif", value=True, key=f"actif_{vtype}")
                    st.session_state.vehicules_actifs[vtype] = actif
                    veh.actif = actif
                with c3:
                    max_v = st.number_input(
                        "Max exemplaires", min_value=0, max_value=20,
                        value=0, step=1, key=f"max_{vtype}",
                        help="0 = illimité"
                    )
                    st.session_state.max_vehicules[vtype] = max_v if max_v > 0 else None
                    veh.max_exemplaires = max_v if max_v > 0 else None

        # --- Capacité quais ---
        with st.expander("🏭 Capacité des quais par site", expanded=False):
            raw = st.session_state.raw_data
            for site_name, sdata in sorted(raw["sites"].items()):
                if not sdata.get("presence_quai", False):
                    continue
                default_cap = config.SITE_DOCK_OVERRIDES.get(site_name, config.DEFAULT_DOCK_CAPACITY)
                if site_name.startswith(config.HSJ_SUBDOCK_SITES_PREFIX):
                    default_cap = config.HSJ_SUBDOCK_CAPACITY
                cap = st.number_input(
                    f"{site_name}", min_value=1, max_value=20,
                    value=st.session_state.dock_capacities.get(site_name, default_cap),
                    step=1, key=f"dock_{site_name}"
                )
                st.session_state.dock_capacities[site_name] = cap
                # Mettre à jour le modèle
                if site_name in st.session_state.sites_models:
                    st.session_state.sites_models[site_name].capacite_quai = cap


# ============================================================================
# ONGLET 3 — SIMULATION
# ============================================================================
with tabs[2]:
    if not st.session_state.data_loaded:
        st.info("Veuillez d'abord charger un fichier valide dans l'onglet **Import & Contrôles**.")
    elif st.session_state.import_errors:
        st.error("Des erreurs bloquantes empêchent la simulation. Corrigez-les dans l'onglet Import.")
    else:
        st.subheader("Configuration et lancement de la simulation")

        raw = st.session_state.raw_data
        fonctions = st.session_state.fonctions_disponibles

        # Sélection des jours
        col_jours, col_fonctions = st.columns(2)
        with col_jours:
            st.markdown("**Jours à simuler**")
            jours_selects = {}
            for idx, nom in config.DAY_NAMES.items():
                # Vérifier si des flux existent ce jour-là
                has_flux = any(
                    f.get("quantites", {}).get(idx, 0)
                    for f in raw["flux_brut"]
                    if f.get("nature", "").strip() == "Volume"
                )
                jours_selects[idx] = st.checkbox(nom, value=has_flux and idx < 5, key=f"jour_{idx}")

        with col_fonctions:
            st.markdown("**Fonctions support à inclure**")
            fonctions_selectees = {}
            for fn in fonctions:
                fonctions_selectees[fn] = st.checkbox(fn, value=True, key=f"fn_{fn}")

        jours_a_simuler = [idx for idx, sel in jours_selects.items() if sel]
        fns_actives = [fn for fn, sel in fonctions_selectees.items() if sel]

        if not jours_a_simuler:
            st.warning("Sélectionnez au moins un jour à simuler.")
        elif not fns_actives:
            st.warning("Sélectionnez au moins une fonction support.")
        else:
            st.markdown(f"**{len(jours_a_simuler)} jour(s) sélectionné(s)** · "
                        f"**{len(fns_actives)} fonction(s) active(s)**")

            # Bouton contrôles préalables
            if st.button("🔍 Lancer les contrôles préalables", type="secondary"):
                with st.spinner("Vérification de la faisabilité des flux…"):
                    matrix_dur_corr = appliquer_facteur_circulation(
                        raw["matrix_dur"],
                        st.session_state.circulation_factor
                    )
                    all_infaisables = []
                    for day_idx in jours_a_simuler:
                        flux_actifs = get_active_flux(
                            raw["flux_brut"], day_idx, fns_actives,
                            raw["contenants"], st.session_state.circulation_factor
                        )
                        infaisables = detecter_flux_infaisables(
                            flux_actifs,
                            st.session_state.vehicules_models,
                            st.session_state.sites_models,
                            matrix_dur_corr,
                            st.session_state.circulation_factor,
                        )
                        for inf in infaisables:
                            inf["jour"] = config.DAY_NAMES[day_idx]
                        all_infaisables.extend(infaisables)

                    st.session_state.flux_infaisables = all_infaisables

                if all_infaisables:
                    st.error(f"⛔ {len(all_infaisables)} flux infaisable(s) détecté(s).")
                    df_inf = pd.DataFrame(all_infaisables)
                    st.dataframe(df_inf, use_container_width=True)
                else:
                    st.success("✅ Tous les flux sont faisables. Vous pouvez lancer la simulation.")

            # Bouton simulation
            btn_disabled = bool(st.session_state.flux_infaisables)
            if st.button("🚀 Lancer la simulation", type="primary", disabled=btn_disabled):
                _run_simulation(jours_a_simuler, fns_actives)


def _run_simulation(jours_a_simuler: list, fns_actives: list):
    """Lance la simulation pour les jours et fonctions sélectionnés."""
    raw = st.session_state.raw_data
    resultats = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    matrix_dur_corr = appliquer_facteur_circulation(
        raw["matrix_dur"],
        st.session_state.circulation_factor
    )

    for i, day_idx in enumerate(jours_a_simuler):
        nom_jour = config.DAY_NAMES[day_idx]
        pct_base = i / len(jours_a_simuler)
        pct_step = 1 / len(jours_a_simuler)

        status_text.text(f"Jour {i+1}/{len(jours_a_simuler)} — {nom_jour} — Préparation des flux…")
        progress_bar.progress(pct_base + pct_step * 0.05)

        # Flux actifs
        flux_actifs = get_active_flux(
            raw["flux_brut"], day_idx, fns_actives,
            raw["contenants"], st.session_state.circulation_factor
        )
        tournees_mutualisees = get_tournees_mutualisees(flux_actifs)

        def _cb(pct, msg):
            progress_bar.progress(pct_base + pct_step * (0.1 + pct * 0.7))
            status_text.text(f"{nom_jour} — {msg}")

        status_text.text(f"{nom_jour} — Construction des tournées…")

        # Optimisation
        planning = optimizer_run(
            flux_actifs=flux_actifs,
            vehicules=st.session_state.vehicules_models,
            sites=st.session_state.sites_models,
            contenants=st.session_state.contenants_models,
            matrix_dur=matrix_dur_corr,
            matrix_dist=raw["matrix_dist"],
            rh=st.session_state.rh_params,
            tournees_mutualisees=tournees_mutualisees,
            progress_callback=_cb,
        )

        status_text.text(f"{nom_jour} — Reconstruction des tournées détaillées…")
        progress_bar.progress(pct_base + pct_step * 0.82)

        tournees = construire_tournees_finales(
            planning,
            st.session_state.vehicules_models,
            st.session_state.sites_models,
            st.session_state.contenants_models,
            matrix_dur_corr,
            raw["matrix_dist"],
        )

        status_text.text(f"{nom_jour} — Affectation des postes chauffeurs…")
        progress_bar.progress(pct_base + pct_step * 0.90)

        postes = affecter_postes(
            tournees,
            st.session_state.vehicules_models,
            st.session_state.rh_params,
        )

        status_text.text(f"{nom_jour} — Planning des quais…")
        progress_bar.progress(pct_base + pct_step * 0.95)

        dock_planning = build_dock_planning(postes, st.session_state.sites_models, st.session_state.vehicules_models)
        conflits = detecter_conflits_quai(dock_planning, st.session_state.sites_models)

        # Calcul des métriques
        flux_transportes = list(set(
            fid for t in tournees for fid in t.flux_ids
        ))
        flux_non_servis_ids = planning.flux_non_affectes
        flux_non_servis_list = [
            {"id_flux": fid, "site_depart": "", "site_arrivee": "",
             "raison": "Non affecté par l'optimiseur", "contrainte": "Compatibilité"}
            for fid in flux_non_servis_ids
        ]
        nb_actifs = len(flux_actifs)
        taux_svc = (len(flux_transportes) / nb_actifs * 100) if nb_actifs else 100

        km_total = sum(t.km_total for t in tournees)
        km_vide = sum(t.km_vide for t in tournees)
        nb_desinf = sum(t.nb_desinfections for t in tournees)

        erreurs_conformite = []
        for c in conflits:
            erreurs_conformite.append({
                "type": "CONFLIT_QUAI",
                "statut": "ALERTE",
                "detail": f"Site {c['site']} : {c['nb_vehicules']} véhicules simultanés > capacité {c['capacite']}",
                "concerne": c["site"],
                "gravite": "MOYEN",
                "action": "Décaler les créneaux de livraison sur ce site",
            })

        if flux_non_servis_list:
            erreurs_conformite.append({
                "type": "FLUX_NON_SERVIS",
                "statut": "ERREUR",
                "detail": f"{len(flux_non_servis_list)} flux non pris en charge",
                "concerne": str(flux_non_servis_ids[:5]),
                "gravite": "CRITIQUE",
                "action": "Vérifier la compatibilité véhicule/flux et la fenêtre horaire",
            })

        res = ResultatJour(
            jour=nom_jour,
            jour_idx=day_idx,
            tournees=tournees,
            postes=postes,
            flux_transportes=flux_transportes,
            flux_non_servis=flux_non_servis_list,
            nb_vehicules=len(set(t.type_vehicule for t in tournees)),
            nb_postes=len(postes),
            km_total=km_total,
            km_vide=km_vide,
            nb_desinfections=nb_desinf,
            taux_service=round(taux_svc, 1),
            erreurs_conformite=erreurs_conformite,
        )
        resultats.append(res)
        progress_bar.progress(pct_base + pct_step)

    st.session_state.resultats = resultats
    st.session_state.simulation_done = True
    progress_bar.progress(1.0)
    status_text.text("✅ Simulation terminée !")
    st.success(f"Simulation de {len(resultats)} jour(s) complétée avec succès.")
    st.rerun()


# ============================================================================
# ONGLET 4 — RÉSULTATS
# ============================================================================
with tabs[3]:
    if not st.session_state.simulation_done or not st.session_state.resultats:
        st.info("Lancez une simulation dans l'onglet **Simulation** pour voir les résultats.")
    else:
        resultats = st.session_state.resultats

        # Sélecteur de jour
        jours_dispo = [r.jour for r in resultats]
        jour_sel = st.selectbox("Sélectionner le jour", jours_dispo, key="jour_sel_resultats")
        res = next((r for r in resultats if r.jour == jour_sel), resultats[0])

        # Métriques clés
        st.markdown("### Métriques clés")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        metriques = [
            (c1, res.nb_vehicules, "Véhicules"),
            (c2, res.nb_postes, "Postes chauffeurs"),
            (c3, f"{res.km_total:.0f}", "Km totaux"),
            (c4, f"{res.km_vide:.0f}", "Km à vide"),
            (c5, f"{res.taux_service:.1f}%", "Taux de service"),
            (c6, res.nb_desinfections, "Désinfections"),
        ]
        for col, val, label in metriques:
            with col:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="value">{val}</div>
                    <div class="label">{label}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("---")

        # Onglets résultats
        r_tabs = st.tabs(["📅 Gantt", "⏱️ Timeline détaillée", "🏭 Quais", "❌ Flux non servis"])

        with r_tabs[0]:
            st.plotly_chart(make_gantt_postes(res.postes, f"Gantt — {res.jour}"),
                           use_container_width=True)

        with r_tabs[1]:
            if res.postes:
                poste_labels = [f"Poste {p.id_poste} — {p.type_vehicule}" for p in res.postes]
                poste_sel = st.selectbox("Sélectionner un poste", poste_labels, key="poste_sel")
                poste_idx = poste_labels.index(poste_sel)
                poste = res.postes[poste_idx]
                st.plotly_chart(make_timeline_poste(poste), use_container_width=True)
            else:
                st.info("Aucun poste à afficher.")

        with r_tabs[2]:
            raw = st.session_state.raw_data
            dock_planning = build_dock_planning(
                res.postes, st.session_state.sites_models, st.session_state.vehicules_models
            )
            if dock_planning:
                df_dock = pd.DataFrame(dock_planning)
                df_dock["heure_arrivee"] = df_dock["heure_arrivee"].apply(minutes_to_hhmm)
                df_dock["heure_debut_quai"] = df_dock["heure_debut_quai"].apply(minutes_to_hhmm)
                df_dock["heure_fin_quai"] = df_dock["heure_fin_quai"].apply(minutes_to_hhmm)
                st.dataframe(df_dock, use_container_width=True)
            else:
                st.info("Aucune occupation de quai à afficher.")

        with r_tabs[3]:
            if res.flux_non_servis:
                st.error(f"⚠️ {len(res.flux_non_servis)} flux non servi(s).")
                df_ns = pd.DataFrame(res.flux_non_servis)
                st.dataframe(df_ns, use_container_width=True)
            else:
                st.success("✅ Tous les flux ont été pris en charge.")

        # Graphique multi-jours
        if len(resultats) > 1:
            st.markdown("---")
            st.markdown("### Vue multi-jours")
            chart_data = [
                {
                    "jour": r.jour,
                    "nb_vehicules": r.nb_vehicules,
                    "nb_postes": r.nb_postes,
                    "km_total": r.km_total,
                }
                for r in resultats
            ]
            st.plotly_chart(make_synthese_chart(chart_data), use_container_width=True)


# ============================================================================
# ONGLET 5 — EXPORT
# ============================================================================
with tabs[4]:
    if not st.session_state.simulation_done or not st.session_state.resultats:
        st.info("Lancez une simulation dans l'onglet **Simulation** pour générer l'export.")
    else:
        st.subheader("Export des résultats")
        st.markdown(
            "Cliquez sur le bouton ci-dessous pour générer et télécharger le fichier Excel "
            "contenant tous les onglets de résultats (tournées, chauffeurs, quais, flux, indicateurs)."
        )

        if st.button("📥 Générer le fichier Excel de résultats", type="primary"):
            with st.spinner("Génération du fichier Excel en cours…"):
                try:
                    raw = st.session_state.raw_data
                    # Construire l'index flux
                    flux_actifs_all = []
                    for res in st.session_state.resultats:
                        fa = get_active_flux(
                            raw["flux_brut"], res.jour_idx,
                            st.session_state.fonctions_disponibles,
                            raw["contenants"]
                        )
                        flux_actifs_all.extend(fa)
                    flux_by_id = {f.id_flux: f for f in flux_actifs_all}

                    excel_bytes = generate_excel_results(
                        resultats=st.session_state.resultats,
                        flux_by_id=flux_by_id,
                        vehicules_data=raw["vehicules"],
                        sites_data=raw["sites"],
                        rh=st.session_state.rh_params,
                    )

                    st.download_button(
                        label="⬇️ Télécharger OptiFLUX_Resultats.xlsx",
                        data=excel_bytes,
                        file_name="OptiFLUX_Resultats.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                    st.success("Fichier généré avec succès !")
                except Exception as e:
                    st.error(f"Erreur lors de la génération : {e}")
                    logger.exception("Erreur génération Excel")

        # Récapitulatif des résultats
        st.markdown("---")
        st.markdown("### Récapitulatif de la simulation")
        for res in st.session_state.resultats:
            with st.expander(f"📋 {res.jour} — {len(res.flux_transportes)} flux servis / {res.nb_vehicules} véhicules"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Taux de service", f"{res.taux_service:.1f}%")
                c2.metric("Km totaux", f"{res.km_total:.0f} km")
                c3.metric("Désinfections", res.nb_desinfections)
                c4.metric("Flux non servis", len(res.flux_non_servis))
                if res.flux_non_servis:
                    st.error("⚠️ Cette simulation contient des flux non servis — solution invalide.")
                else:
                    st.success("✅ Solution valide — 100% des flux servis.")
