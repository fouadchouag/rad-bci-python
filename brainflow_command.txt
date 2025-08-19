# plugins/bci_metrics_viewer.py
# -*- coding: utf-8 -*-

import json, csv, os, numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QSizePolicy, QStyle
)
from PyQt5.QtCore import Qt, QTimer

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


def _html_confusion(cm, labels):
    """Retourne une petite table HTML de la matrice de confusion."""
    cm = np.asarray(cm, dtype=float)
    if cm.ndim != 2 or cm.shape[0] != cm.shape[1]:
        return "<i>Invalid confusion matrix shape.</i>"

    k = cm.shape[0]
    labels = list(labels or [f"Cls{i}" for i in range(k)])

    # Ajuste la longueur des labels au carré (coupe ou pad)
    if len(labels) < k:
        labels = labels + [f"Cls{i}" for i in range(len(labels), k)]
    elif len(labels) > k:
        labels = labels[:k]

    def th(s): return f'<th style="padding:4px 6px; text-align:center; background:#f6f8fb; border-bottom:1px solid #d0d7de;">{s}</th>'

    rows = []
    head = '<tr>' + th('True \\ Pred') + ''.join(th(l) for l in labels) + '</tr>'
    rows.append(head)

    for i in range(k):
        row = [th(labels[i])]
        for j in range(k):
            v = int(cm[i, j])
            style = 'background:#e9f9f0;' if i == j else ''
            row.append(f'<td style="padding:4px 6px; text-align:center; {style}">{v}</td>')
        rows.append('<tr>' + ''.join(row) + '</tr>')

    table = f'''
    <table cellspacing="0" cellpadding="0" style="border-collapse:collapse; border:1px solid #e5e9f0;">
      {''.join(rows)}
    </table>'''
    return table


def _to_float(x, default=np.nan):
    try:
        return float(x)
    except Exception:
        return float(default)


def _to_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return int(default)


class BCI_MetricsViewer(BasePlugin):
    """
    Affiche les métriques d'un modèle entraîné (venant de BCI_Trainer.report).

    Entrées:
      - report : dict  (obligatoire)
      - dataset : dict (optionnel, utilisé pour récupérer y_names pour l'affichage)

    UI:
      - Résumé (CV mean±std, bal-acc, F1, N, K, algo, folds)
      - Matrice de confusion (CV)
      - Accuracies par classe
      - Boutons Export (JSON du report, CSV confusion + per-class)
    """
    name = "BCI_MetricsViewer"
    language = "Python"
    category = "BCI/Utils"

    def setup(self):
        self.inputs["report"]  = BehaviorSubject(None)
        self.inputs["dataset"] = BehaviorSubject(None)

        self._lbl_head = None
        self._lbl_cm = None
        self._lbl_pc = None

        self._last_report = None
        self._y_names = None

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        # summary line
        self._lbl_head = QLabel("Waiting for report…")
        v.addWidget(self._lbl_head)

        # confusion
        self._lbl_cm = QLabel("")
        self._lbl_cm.setTextFormat(Qt.RichText)
        self._lbl_cm.setWordWrap(True)
        v.addWidget(self._lbl_cm)

        # per-class acc
        self._lbl_pc = QLabel("")
        v.addWidget(self._lbl_pc)

        # buttons
        rbtn = QHBoxLayout()
        b_json = UiKit.make_btn("Export JSON", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        b_json.clicked.connect(self._on_export_json); rbtn.addWidget(b_json)
        b_csv  = UiKit.make_btn("Export CSV (cm + per-class)", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        b_csv.clicked.connect(self._on_export_csv); rbtn.addWidget(b_csv)
        rbtn.addStretch(1); v.addLayout(rbtn)

        root.addWidget(CollapsibleSection("Model metrics", panel, collapsed=False))
        return w

    def execute(self, **kw):
        rep = kw.get("report", None)
        ds  = kw.get("dataset", None)

        # y_names depuis dataset si dispo
        if isinstance(ds, dict):
            yn = ds.get("y_names", None)
            if yn is not None:
                try:
                    self._y_names = list(yn)
                except Exception:
                    pass

        if not isinstance(rep, dict):
            return {}

        # Mémorise et programme MAJ UI dans le thread Qt (évite crash cross-thread)
        self._last_report = rep
        QTimer.singleShot(0, self._update_ui_safe)
        return {}

    # ---------- UI update (toujours dans thread Qt) ----------
    def _update_ui_safe(self):
        rep = self._last_report or {}
        # Labels (ids) et noms humains si disponibles
        labels = rep.get("labels", None)
        names = None
        if labels is not None and self._y_names is not None:
            try:
                names = [
                    (self._y_names[int(i)] if 0 <= int(i) < len(self._y_names) else str(i))
                    for i in labels
                ]
            except Exception:
                try:
                    names = [str(i) for i in labels]
                except Exception:
                    names = None
        elif self._y_names is not None:
            names = list(self._y_names)

        # Résumé (robuste aux None/NaN)
        m = _to_float(rep.get("cv_mean", np.nan))
        s = _to_float(rep.get("cv_std",  np.nan))
        ba = _to_float(rep.get("cv_bal_acc", np.nan))
        f1m = _to_float(rep.get("cv_f1_macro", np.nan))
        N = _to_int(rep.get("N", 0))
        K = _to_int(rep.get("K", 0))
        algo = str(rep.get("algo","?"))
        folds = _to_int(rep.get("cv_folds", 0))

        hold = rep.get("holdout", None)
        if isinstance(hold, dict):
            ha = _to_float(hold.get("acc", np.nan))
            hba = _to_float(hold.get("bal_acc", np.nan))
            hf1 = _to_float(hold.get("f1_macro", np.nan))
            extra = f" | Hold-out acc={ha:.3f}, bal_acc={hba:.3f}, f1m={hf1:.3f}"
        else:
            extra = ""

        if self._lbl_head:
            self._lbl_head.setText(
                f"CV={m:.3f} ± {s:.3f} | BalAcc={ba:.3f} | F1m={f1m:.3f} | "
                f"N={N} | K={K} | Algo={algo} | folds={folds}{extra}"
            )

        # Confusion (valide carrée)
        cm = rep.get("cv_confusion", None)
        if self._lbl_cm:
            if cm is not None:
                try:
                    arr = np.asarray(cm)
                    html = _html_confusion(arr, names)
                    self._lbl_cm.setText(html)
                except Exception:
                    self._lbl_cm.setText("<i>Confusion: error rendering.</i>")
            else:
                self._lbl_cm.setText("<i>No confusion matrix in report.</i>")

        # Per-class acc (robuste)
        if self._lbl_pc:
            pca = rep.get("cv_per_class_acc", None)
            if pca is None:
                self._lbl_pc.setText("")
            else:
                try:
                    pca = list(map(_to_float, pca))
                    if names is None:
                        names = [f"Cls{i}" for i in range(len(pca))]
                    # Harmonise longueurs
                    if len(names) < len(pca):
                        names = names + [f"Cls{i}" for i in range(len(names), len(pca))]
                    elif len(names) > len(pca):
                        names = names[:len(pca)]
                    txt = "Per-class acc: " + " | ".join(
                        f"{names[i]}={pca[i]:.3f}" for i in range(len(pca))
                    )
                    self._lbl_pc.setText(txt)
                except Exception:
                    self._lbl_pc.setText("")

    # ---------- exports ----------
    def _on_export_json(self):
        if not isinstance(self._last_report, dict):
            return
        path, _ = QFileDialog.getSaveFileName(None, "Export metrics (JSON)", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_report, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _on_export_csv(self):
        if not isinstance(self._last_report, dict):
            return

        # Choix du fichier principal (confusion)
        path, _ = QFileDialog.getSaveFileName(None, "Export confusion CSV", "", "CSV (*.csv)")
        if not path:
            return

        try:
            cm = np.asarray(self._last_report.get("cv_confusion", []))
            if cm.ndim != 2 or cm.shape[0] != cm.shape[1] or cm.size == 0:
                # fichier vide propre si pas de CM valide
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f); w.writerow(["Invalid or empty confusion matrix"])
                return

            labels = self._last_report.get("labels", None)
            if labels is not None and self._y_names is not None:
                try:
                    names = [
                        (self._y_names[int(i)] if 0 <= int(i) < len(self._y_names) else str(i))
                        for i in labels
                    ]
                except Exception:
                    names = [str(i) for i in labels]
            elif self._y_names is not None:
                names = list(self._y_names)
            else:
                names = [f"Cls{i}" for i in range(cm.shape[0])]

            # Harmonise longueur noms / taille matrice
            k = cm.shape[0]
            if len(names) < k:
                names = names + [f"Cls{i}" for i in range(len(names), k)]
            elif len(names) > k:
                names = names[:k]

            # confusion
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([""] + names)
                for i in range(k):
                    w.writerow([names[i]] + list(map(int, cm[i].tolist())))

            # per-class
            base, _ = os.path.splitext(path)
            path2 = base + "_perclass.csv"
            pca = self._last_report.get("cv_per_class_acc", [])
            with open(path2, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["class","acc"])
                for i, acc in enumerate(pca):
                    nm = names[i] if i < len(names) else f"Cls{i}"
                    w.writerow([nm, _to_float(acc)])

        except Exception:
            pass
