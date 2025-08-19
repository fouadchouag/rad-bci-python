# plugins/riemann_ts_apply_plugin.py
# -*- coding: utf-8 -*-
"""
RiemannTSApply — applique la Tangent Space pour obtenir des features 1D.
Inputs:
  - ts_transform : TangentSpace entraînée (pyRiemann)
  - cov          : ndarray (n_ch, n_ch)
Outputs:
  - features     : 1D ndarray
  - features_dim : int
"""
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

class RiemannTSApplyPlugin(BasePlugin):
    name = "RiemannTSApply"
    language = "Python"
    category = "ML / Riemann"

    def setup(self):
        self.inputs["ts_transform"] = BehaviorSubject(None)
        self.inputs["cov"] = BehaviorSubject(None)
        self.outputs["features"] = BehaviorSubject(None)
        self.outputs["features_dim"] = BehaviorSubject(None)

    def execute(self, inputs):
        ts = inputs.get("ts_transform"); cov = inputs.get("cov")
        if ts is None or cov is None: return
        C = np.asarray(cov)
        if C.ndim != 2 or C.shape[0] != C.shape[1]: return
        try:
            feat = ts.transform(C[np.newaxis, ...])[0]  # (n_feat,)
            self.outputs["features"].on_next(feat)
            self.outputs["features_dim"].on_next(int(feat.shape[0]))
        except Exception as e:
            print("[RiemannTSApply] transform error:", e)
