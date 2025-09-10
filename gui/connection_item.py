# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QGraphicsPathItem
from PyQt5.QtGui import QPainterPath, QPen, QColor
from PyQt5.QtCore import Qt, QTimer, QPointF

import numpy as np
try:
    import mne
    _HAVE_MNE = True
except Exception:
    _HAVE_MNE = False


class ConnectionItem(QGraphicsPathItem):
    """Relie un output pin → input pin et s’abonne Rx pour propager les valeurs.

    Valide:
      - input unique (un seul câble par entrée),
      - compatibilité par 'famille' (raw/segment/sfreq/…),
      - garde-fou runtime **soft** (log + coercition) sans bloquer inutilement,
      - support de pin.family_hint si fourni par NodeItem/Plugin.

    Particularités:
      - Pour 'segment', on coerce automatiquement vers ndarray float32 2D (n_ch, n_samples),
        contigu, sans memmap, NaN/Inf → 0.
      - 'segment_or_raw' est détecté dynamiquement à chaque frame.
    """

    # ---- Style global ----
    LINE_COLOR           = QColor("#000000")   # noir
    LINE_COLOR_HOVER     = QColor("#F70505")   # au survol
    LINE_COLOR_SELECTED  = QColor("#000000")   # noir aussi en sélection
    LINE_WIDTH           = 2.0
    LINE_WIDTH_HOVER     = 2.6
    LINE_WIDTH_SELECTED  = 3.0
    COSMETIC             = True  # épaisseur indépendante du zoom

    # ---- Règles de compatibilité par "famille" de pins (noms normalisés) ----
    # ⚠️ NE PAS inclure "data" ici: on utilise family_hint("segment_or_raw") côté NodeItem/Plugin
    _PIN_FAMILIES = {
        "raw":       {"raw", "eeg", "x"},
        "segment":   {"segment", "segments", "window", "trial", "epoch", "sample"},
        "sfreq":     {"sfreq", "fs", "sampling_rate", "sample_rate", "sf"},
        "ch_names":  {"ch_names", "channels", "chan_names", "labels", "names"},
        "features":  {"features", "feature", "embedding", "vec", "x_vec"},
        "cov":       {"covariance", "cov", "c"},
        "model":     {"model", "clf", "classifier", "estimator"},
        "label":     {"label", "labels", "y", "target", "class"},
        "status":    {"status"},
        "feature_transform": {"feature_transform", "csp", "feat_transform"},
        "ts_transform":      {"ts_transform", "tspace", "tangent"},
        "segment_or_raw": {"segment_or_raw"},
    }

    # Compatibilités souples (ex: "segment_or_raw" accepte segment ET raw)
    _COMPAT = {
        ("segment_or_raw", "segment"): True,
        ("segment_or_raw", "raw"): True,
        ("segment", "segment_or_raw"): True,
        ("raw", "segment_or_raw"): True,
    }

    def __init__(self, output_pin, input_pin):
        # Valide avant l'init graphique
        self.output_pin = output_pin
        self.input_pin  = input_pin
        self._validate_or_raise()

        super().__init__()

        self.subscription = None
        self._hovering = False

        # Toujours sous les nœuds
        self.setZValue(-1000)

        # Survol + sélection
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, True)

        # Stylos
        self._pen_normal   = QPen(self.LINE_COLOR, self.LINE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self._pen_hover    = QPen(self.LINE_COLOR_HOVER, self.LINE_WIDTH_HOVER, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self._pen_selected = QPen(self.LINE_COLOR_SELECTED, self.LINE_WIDTH_SELECTED, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if self.COSMETIC:
            self._pen_normal.setCosmetic(True)
            self._pen_hover.setCosmetic(True)
            self._pen_selected.setCosmetic(True)

        self.setPen(self._pen_normal)
        self.update_path()

        # Suivi des pins
        self._timer = QTimer()
        self._timer.timeout.connect(self.update_path)
        self._timer.start(33)

        # Rx
        self._connect_rx()

    # ----------------- Helpers normalisation / coercition -----------------
    def _coerce_segment(self, x):
        """Coerce vers ndarray float32 2D (n_ch, n_samples), contigu, sans memmap, NaN→num."""
        if x is None:
            return None
        try:
            arr = np.asarray(x)
        except Exception:
            return None
        if arr.ndim == 0:
            return None
        if arr.ndim == 1:
            arr = arr[np.newaxis, :]
        # matérialise si memmap
        if isinstance(arr.base, np.memmap):
            arr = np.array(arr, copy=True)
        # dtype
        if arr.dtype != np.float32:
            arr = arr.astype(np.float32, copy=False)
        # NaN/Inf → 0
        if not np.isfinite(arr).all():
            arr = np.nan_to_num(arr, copy=False)
        # contigu
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
        # empty windows → None pour éviter propagation vide
        if arr.shape[1] == 0:
            return None
        return arr

    def _coerce_value(self, expected_family: str, val):
        """Coercion par famille; retourne la valeur (potentiellement) transformée."""
        if expected_family == "segment":
            return self._coerce_segment(val)
        if expected_family == "sfreq":
            try:
                f = float(val)
                return f if np.isfinite(f) else None
            except Exception:
                return None
        if expected_family == "ch_names":
            if val is None:
                return None
            if isinstance(val, (list, tuple, np.ndarray)):
                out = []
                for x in val:
                    try:
                        out.append(str(x))
                    except Exception:
                        pass
                return out
            return None
        # 'raw' : pas de coercion (on laisse tel quel)
        # autres familles: passthrough
        return val

    def _detect_family_from_value(self, val):
        """Détecte 'segment' ou 'raw' sur la base de la valeur (pour segment_or_raw)."""
        # raw: objet MNE like
        if _HAVE_MNE and hasattr(val, "get_data"):
            return "raw"
        if hasattr(val, "get_data"):  # fallback si pas mne importé
            return "raw"
        # segment: array-like 1D/2D
        try:
            a = np.asarray(val)
            if a.ndim in (1, 2):
                return "segment"
        except Exception:
            pass
        return None

    # ----------------- Validation (création) -----------------
    def _normalize(self, s: str) -> str:
        return (s or "").strip().lower()

    def _family_from_name(self, pin_name: str) -> str:
        n = self._normalize(pin_name)
        for fam, names in self._PIN_FAMILIES.items():
            if n == fam or n in names:
                return fam
        return n  # fallback: stricte égalité sur le nom normalisé

    def _family_of_pin(self, pin) -> str:
        # 1) priorité au hint posé par NodeItem / plugin
        hint = getattr(pin, "family_hint", None)
        if isinstance(hint, str) and hint.strip():
            return self._normalize(hint)
        # 2) sinon, déduire via le nom
        name = getattr(pin, "name", None) or getattr(pin, "pin_name", None)
        return self._family_from_name(name or "")

    def _families_compatible(self, f_out: str, f_in: str) -> bool:
        if f_out == f_in:
            return True
        return self._COMPAT.get((f_out, f_in), False)

    def _input_already_connected(self) -> bool:
        """Vérifie s'il existe déjà une connexion vers cet input dans la scène."""
        sc = getattr(self.input_pin, "scene", lambda: None)()
        if sc is None:
            return False
        for it in sc.items():
            if isinstance(it, ConnectionItem) and it is not self and getattr(it, "input_pin", None) is self.input_pin:
                return True
        return False

    def _validate_or_raise(self):
        if self.output_pin is None or self.input_pin is None:
            raise ValueError("Pins invalides.")

        # Input → une seule connexion
        if self._input_already_connected():
            raise ValueError("Cet input a déjà une connexion.")

        # Famille compatible ?
        out_fam = self._family_of_pin(self.output_pin)
        in_fam  = self._family_of_pin(self.input_pin)

        if not self._families_compatible(out_fam, in_fam):
            on  = getattr(self.output_pin, "name", None) or getattr(self.output_pin, "pin_name", None) or "?"
            inn = getattr(self.input_pin,  "name", None) or getattr(self.input_pin,  "pin_name",  None) or "?"
            raise ValueError(f"Incompatibilité de pins: '{on}' ({out_fam}) → '{inn}' ({in_fam})")

        # Évite boucle sur le même nœud
        try:
            if self.output_pin.parentItem() is self.input_pin.parentItem():
                raise ValueError("Connexion sur le même nœud interdite.")
        except Exception:
            pass

    # ----------------- Validation runtime (soft) -----------------
    def _runtime_ok(self, expected_family: str, val) -> bool:
        """Valide grossièrement la valeur selon la famille attendue. Soft: True si None pour laisser l'init."""
        try:
            if expected_family == "segment":
                if val is None:
                    return True  # pas encore de data
                a = np.asarray(val)
                return (a.ndim == 2 and a.shape[1] > 0)
            if expected_family == "raw":
                if val is None:
                    return True
                if _HAVE_MNE:
                    return hasattr(val, "get_data")
                return hasattr(val, "get_data")
            if expected_family == "sfreq":
                if val is None:
                    return True
                f = float(val)
                return np.isfinite(f)
            if expected_family == "ch_names":
                return (val is None) or (isinstance(val, (list, tuple)) and all(isinstance(x, str) for x in val))
            if expected_family == "features":
                return (val is None) or (isinstance(val, dict) or
                                         (isinstance(val, np.ndarray) and val.ndim in (1, 2)))
            if expected_family == "cov":
                if val is None:
                    return True
                a = np.asarray(val)
                return a.ndim == 2 and a.shape[0] == a.shape[1] and a.shape[0] >= 2
            if expected_family == "label":
                return (val is None) or isinstance(val, (str, int))
            if expected_family == "status":
                return (val is None) or isinstance(val, str)
            # model / feature_transform / ts_transform / autres: tolérant
            return True
        except Exception:
            return False

    # ----------------- Rx -----------------
    def _connect_rx(self):
        out_node = self.output_pin.parentItem().plugin
        in_node  = self.input_pin.parentItem().plugin
        out_pin_name = getattr(self.output_pin, "name", None) or getattr(self.output_pin, "pin_name", None)
        in_pin_name  = getattr(self.input_pin,  "name", None) or getattr(self.input_pin,  "pin_name",  None)
        if not out_pin_name or not in_pin_name:
            return

        source = out_node.get_output(out_pin_name)
        if not source:
            return

        expected_family = self._family_of_pin(self.input_pin)

        def _on_val(val):
            fam_eff = expected_family
            # Détection dynamique si l'input déclare 'segment_or_raw'
            if expected_family == "segment_or_raw":
                fam_from_val = self._detect_family_from_value(val)
                if fam_from_val is not None:
                    fam_eff = fam_from_val
                else:
                    # On tente une coercition segment par défaut
                    fam_eff = "segment"

            # Coercion selon la famille effective
            v2 = self._coerce_value(fam_eff, val)

            # Soft validation: on log en WARN si ça ne passe pas, mais on évite le ❌ bloquant
            if not self._runtime_ok(fam_eff, v2):
                print(f"[Connection][WARN] valeur atypique ({fam_eff}) pour "
                      f"{out_node.name}.{out_pin_name} → {in_node.name}.{in_pin_name} ; frame ignorée.")
                return  # ignore juste cette frame

            try:
                in_node.set_input(in_pin_name, v2)
            except Exception as e:
                print(f"[Connection][WARN] set_input a échoué sur {in_node.name}.{in_pin_name}: {e}")

        print(f"[Connection] Subscribe: {out_node.name}.{out_pin_name} → {in_node.name}.{in_pin_name}")
        try:
            self.subscription = source.subscribe(_on_val)
        except Exception as e:
            print(f"[Connection][ERROR] subscribe a échoué: {e}")

    def cleanup(self):
        # Stop timer + Rx
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        if self.subscription:
            try:
                self.subscription.dispose()
            except Exception:
                pass
            self.subscription = None

        # Couper la chaîne en mettant None côté entrée
        try:
            plugin = self.input_pin.parentItem().plugin
            pin_name = getattr(self.input_pin, "name", None) or getattr(self.input_pin, "pin_name", None)
            if plugin and pin_name:
                plugin.set_input(pin_name, None)
        except Exception:
            pass

    # ----------------- Path / dessin -----------------
    def track_both_pins(self):
        self.track_pin(self.input_pin)
        self.track_pin(self.output_pin)

    def track_pin(self, _pin):
        self.update_path()

    def update_path(self):
        if not self.input_pin or not self.output_pin:
            return
        start_point = self.input_pin.scenePos()
        end_point   = self.output_pin.scenePos()

        path = QPainterPath()
        path.moveTo(start_point)
        dx = (end_point.x() - start_point.x()) * 0.5
        ctrl1 = start_point + QPointF(dx, 0)
        ctrl2 = end_point   - QPointF(dx, 0)
        path.cubicTo(ctrl1, ctrl2, end_point)
        self.setPath(path)

    # ----------------- États visuels -----------------
    def _apply_pen(self):
        if self.isSelected():
            self.setPen(self._pen_selected)
        else:
            self.setPen(self._pen_hover if self._hovering else self._pen_normal)

    def itemChange(self, change, value):
        if change == QGraphicsPathItem.ItemSelectedChange:
            self._apply_pen()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self._hovering = True
        if not self.isSelected():
            self.setPen(self._pen_hover)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovering = False
        if not self.isSelected():
            self.setPen(self._pen_normal)
        super().hoverLeaveEvent(event)
