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
    help = {
        'summary': 'Apply a trained Tangent Space transform to project covariance matrices into 1D feature vectors.',
        'usage': 'Connect a trained ts_transform (from RiemannTSTrainer) and a covariance matrix. Outputs a 1D feature vector.',
        'inputs': {
            'ts_transform': 'trained pyRiemann TangentSpace object — must be fitted via RiemannTSTrainer',
            'cov': '2D float [ch x ch] — SPD covariance matrix matching the dimensionality used during TS training',
        },
        'outputs': {
            'features': '1D float array — tangent-space feature vector of dimension n_ch*(n_ch+1)/2',
            'features_dim': 'int — dimensionality of the feature vector',
        },
        'parameters': [],
        'gotchas': [
            'The ts_transform must be fitted (via RiemannTSTrainer) before use; otherwise transform will fail silently.',
            'Input covariance must be SPD and square, matching the number of channels used during TS training.',
            'The covariance is wrapped in a batch dimension internally: ts.transform(C[np.newaxis, ...]).',
            'If either ts_transform or cov is None, the node outputs nothing (no error emitted).',
        ],
    }

    name = "RiemannTSApply"
    language = "Python"
    category = "ML"

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