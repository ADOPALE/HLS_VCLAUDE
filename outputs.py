"""
outputs.py — Génération du fichier Excel de résultats OptiFLUX.

Produit le classeur xlsxwriter avec tous les onglets définis dans config.EXPORT_SHEETS.
"""

from __future__ import annotations
import io
import logging
from typing import Any, Dict, List, Optional

import xlsxwriter

import config
from models import Tournee, PosteChaufeur, Flux, ResultatJour
from time_windows import minutes_to_hhmm

logger = logging.getLogger(__name__)

# Styles de base
HEADER_FORMAT = {
    "bold": True,
    "bg_color": "#1565C0",
    "font_color": "white",
    "border": 1,
    "text_wrap": True,
    "valign": "vcenter",
    "align": "center",
}
ROW_FORMAT_ODD = {"bg_color": "#F5F9FF", "border": 1}
ROW_FORMAT_EVEN = {"bg_color": "white", "border": 1}
ALERT_FORMAT = {"bg_color": "#FFCCCC", "border": 1}
OK_FORMAT = {"bg_color": "#CCFFCC", "border": 1}


def generate_excel_results(
    resultats: List[ResultatJour],
    flux_by_id: Dict[int, Flux],
    vehicules_data: Dict[str, Any],
    sites_data: Dict[str, Any],
    rh: Dict[str, int],
) -> bytes:
    """
    Génère le fichier Excel de résultats complet.

    Args:
        resultats: Liste des résultats par jour simulé.
        flux_by_id: Index des flux par ID.
        vehicules_data: Dict des véhicules.
        sites_data: Dict des sites.
        rh: Paramètres RH.

    Returns:
        Contenu du fichier Excel en bytes (pour téléchargement Streamlit).
    """
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})

    # Formats
    fmt_header = wb.add_format(HEADER_FORMAT)
    fmt_odd = wb.add_format(ROW_FORMAT_ODD)
    fmt_even = wb.add_format(ROW_FORMAT_EVEN)
    fmt_alert = wb.add_format(ALERT_FORMAT)
    fmt_ok = wb.add_format(OK_FORMAT)

    def fmt_row(i):
        return fmt_odd if i % 2 == 0 else fmt_even

    # --- Onglet Synthèse flotte ---
    ws = wb.add_worksheet(config.EXPORT_SHEETS["synthese_flotte"])
    headers = [
        "Jour", "Type de véhicule", "Nombre utilisé", "Nb tournées",
        "Km totaux", "Km à plein", "Km à vide",
        "Temps total (min)", "Taux utilisation (%)", "Nb désinfections",
        "Coût estimé (€)", "Émissions CO₂ (kg)",
    ]
    _write_headers(ws, headers, fmt_header)
    row = 1
    for res in resultats:
        veh_counts: Dict[str, Dict] = {}
        for t in res.tournees:
            vt = t.type_vehicule
            if vt not in veh_counts:
                veh_counts[vt] = {"nb": 0, "tournees": 0, "km": 0, "km_vide": 0,
                                   "temps": 0, "desinf": 0, "cout": 0, "co2": 0}
            veh_counts[vt]["nb"] += 1
            veh_counts[vt]["tournees"] += 1
            veh_counts[vt]["km"] += t.km_total
            veh_counts[vt]["km_vide"] += t.km_vide
            veh_counts[vt]["temps"] += t.heure_fin - t.heure_debut
            veh_counts[vt]["desinf"] += t.nb_desinfections
            vd = vehicules_data.get(vt, {})
            veh_counts[vt]["cout"] += t.km_total * vd.get("cout_carburant", 0)
            veh_counts[vt]["co2"] += t.km_total * vd.get("cout_carbone", 0)

        for vt, stats in sorted(veh_counts.items()):
            fm = fmt_row(row)
            km_plein = stats["km"] - stats["km_vide"]
            # Taux = nb tournées × durée moy / (nb postes × vacation)
            # Approximation : stats["temps"] = somme des durées tournées
            taux_util = min(100.0, (stats["temps"] / (stats["nb"] * max(rh.get("vacation_duration", 450), 1)) * 100)) if stats["nb"] else 0
            ws.write_row(row, 0, [
                res.jour, vt, stats["nb"], stats["tournees"],
                round(stats["km"], 1), round(km_plein, 1), round(stats["km_vide"], 1),
                stats["temps"], round(taux_util, 1), stats["desinf"],
                round(stats["cout"], 2), round(stats["co2"], 2),
            ], fm)
            row += 1

    ws.set_column(0, len(headers) - 1, 16)

    # --- Onglet Synthèse chauffeurs ---
    ws2 = wb.add_worksheet(config.EXPORT_SHEETS["synthese_chauffeurs"])
    headers2 = [
        "Jour", "Poste", "Véhicule", "Heure début", "Heure fin", "Durée (min)",
        "Prise de poste (min)", "Fin de poste (min)", "Pause (min)",
        "Conduite (min)", "Manutention (min)", "Quai (min)",
        "Désinfection (min)", "Attente (min)", "Inoccupé (min)",
        "Taux occupation (%)", "Taux inoccupé (%)",
    ]
    _write_headers(ws2, headers2, fmt_header)
    row2 = 1
    for res in resultats:
        for poste in res.postes:
            fm = fmt_row(row2)
            vac = max(poste.duree_vacation, 1)
            taux_occ = min(100.0, round(
                (poste.temps_conduite + poste.temps_manutention +
                 poste.temps_quai + poste.temps_desinfection) / vac * 100, 1
            ))
            taux_inocc = min(100.0, round(poste.temps_inoccupe / vac * 100, 1))
            ws2.write_row(row2, 0, [
                res.jour, poste.id_poste, poste.type_vehicule,
                minutes_to_hhmm(poste.heure_debut), minutes_to_hhmm(poste.heure_fin),
                poste.duree_vacation,
                poste.temps_prise_poste, poste.temps_fin_poste, poste.temps_pause,
                poste.temps_conduite, poste.temps_manutention, poste.temps_quai,
                poste.temps_desinfection, poste.temps_attente, poste.temps_inoccupe,
                taux_occ, taux_inocc,
            ], fm)
            row2 += 1
    ws2.set_column(0, len(headers2) - 1, 14)

    # --- Onglet Tournées véhicules ---
    ws3 = wb.add_worksheet(config.EXPORT_SHEETS["tournees_vehicules"])
    headers3 = [
        "Jour", "N° Tournée", "Véhicule", "Ordre", "Heure début", "Heure fin",
        "Site départ", "Site arrivée", "Type opération", "Flux IDs",
        "Nb contenants chargés", "Taux rempl. surf. (%)", "Distance (km)", "Durée (min)",
        "À vide ?", "État sanitaire",
    ]
    _write_headers(ws3, headers3, fmt_header)
    row3 = 1
    for res in resultats:
        for t in res.tournees:
            for k, step in enumerate(t.steps):
                fm = fmt_row(row3)
                ws3.write_row(row3, 0, [
                    res.jour, t.id_tournee, t.type_vehicule, k + 1,
                    minutes_to_hhmm(step.heure_debut), minutes_to_hhmm(step.heure_fin),
                    step.site if k == 0 else "",
                    step.site,
                    step.type_operation,
                    ", ".join(str(i) for i in step.flux_ids),
                    step.nb_contenants,
                    f"{step.taux_remplissage_surface*100:.0f}%",
                    round(step.distance_km, 1),
                    step.heure_fin - step.heure_debut,
                    "Oui" if step.est_trajet_vide else "Non",
                    step.statut_sanitaire,
                ], fm)
                row3 += 1
    ws3.set_column(0, len(headers3) - 1, 14)

    # --- Onglet Flux transportés ---
    ws5 = wb.add_worksheet(config.EXPORT_SHEETS["flux_transportes"])
    headers5 = [
        "Jour", "ID flux", "Origine", "Destination", "Fonction support",
        "Contenant", "Nb contenants prévus", "Véhicule", "N° Tournée",
        "Heure collecte", "Heure livraison", "Conformité horaire",
    ]
    _write_headers(ws5, headers5, fmt_header)
    row5 = 1
    for res in resultats:
        flux_info: Dict[int, Dict] = {}
        for t in res.tournees:
            for step in t.steps:
                for fid in step.flux_ids:
                    if fid not in flux_info:
                        flux_info[fid] = {
                            "tournee": t.id_tournee,
                            "vehicule": t.type_vehicule,
                            "collecte": step.heure_debut if step.type_operation == config.OP_CHARGEMENT else None,
                            "livraison": step.heure_fin if step.type_operation == config.OP_DECHARGEMENT else None,
                        }
                    else:
                        if step.type_operation == config.OP_CHARGEMENT:
                            flux_info[fid]["collecte"] = step.heure_debut
                        if step.type_operation == config.OP_DECHARGEMENT:
                            flux_info[fid]["livraison"] = step.heure_fin

        for fid in res.flux_transportes:
            flux = flux_by_id.get(fid)
            if not flux:
                continue
            info = flux_info.get(fid, {})
            collecte = info.get("collecte")
            livraison = info.get("livraison")
            conforme = "Oui"
            if collecte and flux.heure_dispo and collecte < flux.heure_dispo:
                conforme = "Non"
            if livraison and flux.heure_max_livraison and livraison > flux.heure_max_livraison:
                conforme = "Non"
            fm = fmt_ok if conforme == "Oui" else fmt_alert
            ws5.write_row(row5, 0, [
                res.jour, fid, flux.site_depart, flux.site_arrivee,
                flux.fonction_support, flux.type_contenant, flux.quantite,
                info.get("vehicule", ""),
                info.get("tournee", ""),
                minutes_to_hhmm(collecte) if collecte else "",
                minutes_to_hhmm(livraison) if livraison else "",
                conforme,
            ], fm)
            row5 += 1
    ws5.set_column(0, len(headers5) - 1, 16)

    # --- Onglet Flux non servis ---
    ws6 = wb.add_worksheet(config.EXPORT_SHEETS["flux_non_servis"])
    headers6 = ["Jour", "ID flux", "Origine", "Destination", "Raison", "Contrainte"]
    _write_headers(ws6, headers6, fmt_header)
    row6 = 1
    for res in resultats:
        for fns in res.flux_non_servis:
            ws6.write_row(row6, 0, [
                res.jour,
                fns.get("id_flux", ""),
                fns.get("site_depart", ""),
                fns.get("site_arrivee", ""),
                fns.get("raison", ""),
                fns.get("contrainte", ""),
            ], fmt_alert)
            row6 += 1
    ws6.set_column(0, len(headers6) - 1, 20)

    # --- Onglet Indicateurs ---
    ws8 = wb.add_worksheet(config.EXPORT_SHEETS["indicateurs"])
    headers8 = [
        "Jour", "Nb total flux", "Nb total contenants", "Nb flux servis",
        "Taux service (%)", "Km totaux", "Km à plein", "Km à vide",
        "Taux km à vide (%)", "Nb véhicules", "Nb postes", "Nb désinfections",
    ]
    _write_headers(ws8, headers8, fmt_header)
    row8 = 1
    for res in resultats:
        nb_cont = sum(
            flux_by_id[i].quantite for i in res.flux_transportes if i in flux_by_id
        )
        km_plein = res.km_total - res.km_vide
        taux_vide = (res.km_vide / res.km_total * 100) if res.km_total > 0 else 0
        ws8.write_row(row8, 0, [
            res.jour,
            len(res.flux_transportes) + len(res.flux_non_servis),
            nb_cont,
            len(res.flux_transportes),
            round(res.taux_service, 1),
            round(res.km_total, 1),
            round(km_plein, 1),
            round(res.km_vide, 1),
            round(taux_vide, 1),
            res.nb_vehicules,
            res.nb_postes,
            res.nb_desinfections,
        ], fmt_row(row8))
        row8 += 1
    ws8.set_column(0, len(headers8) - 1, 16)

    # --- Onglet Contrôles contraintes ---
    ws7 = wb.add_worksheet(config.EXPORT_SHEETS["controles"])
    headers7 = [
        "Jour", "Type contrôle", "Statut", "Détail",
        "Flux / véhicule concerné", "Gravité", "Action recommandée",
    ]
    _write_headers(ws7, headers7, fmt_header)
    row7 = 1
    for res in resultats:
        for ctrl in res.erreurs_conformite:
            statut = ctrl.get("statut", "ALERTE")
            fm = fmt_alert if statut in ("ERREUR", "ALERTE") else fmt_ok
            ws7.write_row(row7, 0, [
                res.jour,
                ctrl.get("type", ""),
                statut,
                ctrl.get("detail", ""),
                ctrl.get("concerne", ""),
                ctrl.get("gravite", ""),
                ctrl.get("action", ""),
            ], fm)
            row7 += 1
    ws7.set_column(0, len(headers7) - 1, 22)

    # --- Onglet Planning chauffeurs (détail chronologique) ---
    ws_pc = wb.add_worksheet(config.EXPORT_SHEETS["planning_chauffeurs"])
    headers_pc = [
        "Jour", "Poste", "Véhicule", "Ordre",
        "Heure début", "Heure fin", "Durée (min)",
        "Type opération", "Site", "Flux IDs",
        "Nb contenants", "Taux rempl. surf. (%)", "Statut sanitaire",
    ]
    _write_headers(ws_pc, headers_pc, fmt_header)
    row_pc = 1
    for res in resultats:
        for poste in res.postes:
            for k, step in enumerate(poste.steps):
                fm = fmt_row(row_pc)
                ws_pc.write_row(row_pc, 0, [
                    res.jour,
                    poste.id_poste,
                    poste.type_vehicule,
                    k + 1,
                    minutes_to_hhmm(step.heure_debut),
                    minutes_to_hhmm(step.heure_fin),
                    step.heure_fin - step.heure_debut,
                    step.type_operation,
                    step.site,
                    ", ".join(str(i) for i in step.flux_ids) if step.flux_ids else "",
                    step.nb_contenants,
                    f"{step.taux_remplissage_surface * 100:.0f}%" if step.taux_remplissage_surface else "0%",
                    step.statut_sanitaire,
                ], fm)
                row_pc += 1
    ws_pc.set_column(0, len(headers_pc) - 1, 16)

    # --- Onglet Planning quais ---
    ws_pq = wb.add_worksheet(config.EXPORT_SHEETS["planning_quais"])
    headers_pq = [
        "Jour", "Site", "Capacité quai",
        "Heure arrivée", "Heure début quai", "Heure fin quai",
        "Durée quai (min)", "Véhicule", "Poste",
        "Flux IDs",
    ]
    _write_headers(ws_pq, headers_pq, fmt_header)
    row_pq = 1
    for res in resultats:
        for poste in res.postes:
            for step in poste.steps:
                if step.type_operation != config.OP_MISE_A_QUAI:
                    continue
                dur_q = step.heure_fin - step.heure_debut
                fm = fmt_row(row_pq)
                ws_pq.write_row(row_pq, 0, [
                    res.jour,
                    step.site,
                    "",  # capacité non disponible ici
                    minutes_to_hhmm(step.heure_debut),
                    minutes_to_hhmm(step.heure_debut),
                    minutes_to_hhmm(step.heure_fin),
                    dur_q,
                    poste.type_vehicule,
                    poste.id_poste,
                    ", ".join(str(i) for i in step.flux_ids) if step.flux_ids else "",
                ], fm)
                row_pq += 1
    ws_pq.set_column(0, len(headers_pq) - 1, 18)

    wb.close()
    output.seek(0)
    return output.read()


def _write_headers(ws, headers: List[str], fmt) -> None:
    """Écrit la ligne d'en-tête d'un onglet."""
    for i, h in enumerate(headers):
        ws.write(0, i, h, fmt)
    ws.set_row(0, 30)
