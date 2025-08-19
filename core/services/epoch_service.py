# core/services/epoch_service.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import numpy as np
from typing import Optional, Tuple


def _next_pow2(n: int) -> int:
    n = int(max(1, n))
    return 1 << (n-1).bit_length()


class EpochService:
    """
    Découpe des chunks en segments réguliers, avec overlap + lissage (cross-fade).
    - Mode AUTO : calcule seg_len_s à partir de sfreq (≈ 1024 échantillons, arrondi puissance de 2).
    - Mode MANUEL : seg_len_s fourni.
    - hop_s : pas entre segments (par défaut seg_len/2 => 50% overlap).
    - smoothing: applique une fenêtre cosinus sur 10% de bord pour réduire discontinuités.
    """
    def __init__(self, sfreq: float,
                 seg_len_s: Optional[float] = None,
                 hop_s: Optional[float] = None,
                 auto: bool = True,
                 smoothing: bool = True):
        self.sfreq = float(sfreq)
        self.auto = bool(auto)
        self.smoothing = bool(smoothing)

        if self.auto or not seg_len_s:
            target = 1024  # ~4.096s @ 250Hz, ~2.048s @ 500Hz
            seg_samps = _next_pow2(int(target * (self.sfreq / 250.0)))
            self.seg_len = max(128, seg_samps)
        else:
            self.seg_len = max(32, int(round(seg_len_s * self.sfreq)))

        if hop_s is None:
            self.hop = max(1, self.seg_len // 2)  # 50% overlap
        else:
            self.hop = max(1, int(round(hop_s * self.sfreq)))

        self._buf = None  # shape (N, C)
        self._carry_tail = None  # pour cross-fade

        # fenêtre de lissage (10% aux bords)
        if self.smoothing:
            edge = max(1, int(0.1 * self.seg_len))
            win = np.ones(self.seg_len, dtype=np.float32)
            ramp = (1 - np.cos(np.linspace(0, np.pi, edge))) / 2.0
            win[:edge] *= ramp
            win[-edge:] *= ramp[::-1]
            self._win = win
        else:
            self._win = None

        self._produced = 0  # index de segment

    def feed(self, chunk: np.ndarray):
        """
        Ajoute un chunk (n, C). Retourne éventuellement une liste de segments prêts [(seg, t0_idx), ...]
        """
        if chunk is None:
            return []
        if chunk.ndim != 2:
            raise ValueError("chunk doit être shape (n_samples, n_channels)")
        if self._buf is None:
            self._buf = chunk.copy()
        else:
            self._buf = np.vstack([self._buf, chunk])

        out = []
        while self._buf.shape[0] >= self.seg_len + self._produced*self.hop:
            start = self._produced * self.hop
            end = start + self.seg_len
            if end > self._buf.shape[0]:
                break
            seg = self._buf[start:end, :]  # (seg_len, C)
            if self._win is not None:
                seg = seg * self._win[:, None]
            out.append((seg, start))
            self._produced += 1

        # garder un tampon raisonnable (éviter gonflement)
        keep_from = max(0, (self._produced*self.hop) - self.seg_len)
        if keep_from > 0:
            self._buf = self._buf[keep_from:, :]
            self._produced -= keep_from // self.hop
        return out

    def seg_len_seconds(self) -> float:
        return self.seg_len / self.sfreq

    def hop_seconds(self) -> float:
        return self.hop / self.sfreq
