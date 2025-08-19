# core/services/acquisition_manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import threading, time
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np


def _next_pow2(n: int) -> int:
    n = int(max(1, n))
    return 1 << (n - 1).bit_length()


class AcquisitionManager:
    """Service temps réel (LSL/Emulator) avec segmentation & logs remontés au plugin."""
    def __init__(self):
        self._driver: Optional[_BaseDriver] = None
        self.on_info: Callable[[Dict], None] = lambda meta: None
        self.on_segment: Callable[[np.ndarray], None] = lambda seg: None

    def start(self, source: str = "emulator", config: Optional[Dict] = None):
        self.stop()
        cfg = dict(config or {})
        s = (source or "emulator").lower()
        if s == "lsl":
            self._driver = LSLDriver(cfg, self.on_info, self.on_segment)
        elif s == "emulator":
            self._driver = EmulatorDriver(cfg, self.on_info, self.on_segment)
        else:
            raise ValueError(f"Unknown source: {source}")
        self._driver.start()

    def stop(self):
        if self._driver:
            self._driver.stop()
            self._driver = None


# ---------------- Base + segmentation ----------------

class _BaseDriver:
    def __init__(self, cfg: Dict,
                 cb_info: Callable[[Dict], None],
                 cb_seg: Callable[[np.ndarray], None]):
        self.cfg = cfg
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.on_info = cb_info
        self.on_segment = cb_seg

        # segmentation params
        self._sfreq: float = float(cfg.get("sfreq", 250.0))
        self._ch_names: List[str] = list(cfg.get("ch_names", []))
        self._seg_len_s: Optional[float] = cfg.get("seg_len_s", None)
        self._hop_s: Optional[float] = cfg.get("hop_s", None)
        self._smoothing: bool = bool(cfg.get("smoothing", True))
        self._normalize_labels: bool = bool(cfg.get("normalize_labels", True))

        # state
        self._buf = None  # (n_samples, n_ch)
        self._seg_len = 0
        self._hop = 0
        self._win = None

    def _dbg(self, msg: str):
        try:
            self.on_info({"source": self.__class__.__name__.replace("Driver","").lower(),
                          "debug": msg})
        except Exception:
            pass

    def _prepare_segmenter(self):
        sf = float(self._sfreq or 250.0)
        if self._seg_len_s is None:
            target = 256 * (sf / 250.0)  # ~1s @250Hz
            seg = _next_pow2(int(round(target)))
            self._seg_len = max(64, seg)
        else:
            self._seg_len = max(16, int(round(float(self._seg_len_s) * sf)))

        if self._hop_s is None:
            self._hop = max(1, self._seg_len // 2)
        else:
            self._hop = max(1, int(round(float(self._hop_s) * sf)))

        if self._smoothing:
            edge = max(1, int(0.1 * self._seg_len))
            win = np.ones(self._seg_len, dtype=np.float32)
            ramp = (1 - np.cos(np.linspace(0, np.pi, edge))) / 2.0
            win[:edge] *= ramp
            win[-edge:] *= ramp[::-1]
            self._win = win
        else:
            self._win = None

        self._dbg(f"segmenter ready: seg_len={self._seg_len}, hop={self._hop}, sf={self._sfreq:.2f}")

    def _emit_info(self, source: str, reset: bool = True):
        names = list(self._ch_names)
        if self._normalize_labels:
            names = [n.rstrip(".") for n in names]
        meta = {"sfreq": float(self._sfreq), "ch_names": names, "reset": bool(reset), "source": source}
        self.on_info(meta)
        self._dbg(f"[meta emitted] {len(names)}ch @{self._sfreq:.2f}Hz")

    def _feed_samples(self, chunk_ns_c: np.ndarray):
        if chunk_ns_c is None or chunk_ns_c.ndim != 2:
            return
        if self._buf is None:
            self._buf = chunk_ns_c
        else:
            self._buf = np.vstack([self._buf, chunk_ns_c])

        while self._buf.shape[0] >= self._seg_len:
            seg_ns_c = self._buf[:self._seg_len, :]
            self._buf = self._buf[self._hop:, :]
            if self._win is not None:
                seg_ns_c = (seg_ns_c * self._win[:, None]).astype(np.float32, copy=False)
            seg_c_ns = seg_ns_c.T.astype(np.float32, copy=False)
            self.on_segment(seg_c_ns)

    def start(self): raise NotImplementedError
    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._buf = None


# ---------------- LSL driver ----------------

class LSLDriver(_BaseDriver):
    def start(self):
        try:
            import pylsl as lsl
        except Exception as e:
            self.on_info({"source": "lsl", "error": f"pylsl import error: {e}"})
            return

        info_obj = self.cfg.get("lsl_info_obj", None)
        hint_name = (self.cfg.get("lsl_name") or "").strip()
        hint_type = (self.cfg.get("lsl_type") or "EEG").strip() or "EEG"
        hint_n = int(self.cfg.get("hint_n_ch") or 0)
        hint_sf = float(self.cfg.get("hint_sfreq") or 0.0)
        chunk_sz = int(self.cfg.get("chunk", 64))
        pull_timeout = float(self.cfg.get("timeout", 0.2))

        def _hb(phase: str): self._dbg(f"[hb] {phase}")

        def _pick_best_stream() -> Optional["lsl.StreamInfo"]:
            _hb("scan start")
            deadline = time.monotonic() + 4.0
            best = None; best_score = -1
            while time.monotonic() < deadline and not self._stop.is_set():
                try:
                    streams = lsl.resolve_streams(0.6)
                except Exception:
                    streams = []
                if streams:
                    for s in streams:
                        score = 0
                        try:
                            if (s.type() or "").lower() == hint_type.lower(): score += 10
                        except Exception: pass
                        try:
                            if hint_name and (s.name() or "") == hint_name: score += 30
                        except Exception: pass
                        try:
                            if hint_n and int(s.channel_count()) == hint_n: score += 3
                        except Exception: pass
                        try:
                            if hint_sf and int(round(s.nominal_srate() or 0.0)) == int(round(hint_sf)): score += 3
                        except Exception: pass
                        if score > best_score:
                            best, best_score = s, score
                    if best is not None:
                        _hb("scan picked"); return best
                time.sleep(0.15)
            _hb("scan none")
            return best

        def _read_anything(inlet) -> Tuple[Optional[np.ndarray], List[float]]:
            try:
                samples, ts = inlet.pull_chunk(timeout=pull_timeout, max_samples=chunk_sz)
            except Exception:
                samples, ts = [], []
            if samples:
                arr = np.asarray(samples, dtype=np.float32)
                if arr.ndim == 1: arr = arr[:, None]
                self._dbg(f"[pull_chunk] {arr.shape}")
                return arr, list(ts)

            rows = []
            ts_list: List[float] = []
            t0 = time.monotonic()
            while (time.monotonic() - t0) < 0.8 and not self._stop.is_set():
                try:
                    sample, t = inlet.pull_sample(timeout=0.05)
                except Exception:
                    sample, t = None, None
                if sample is not None:
                    rows.append(sample)
                    if t is not None: ts_list.append(float(t))
                    if len(rows) >= max(8, chunk_sz // 2): break
            if rows:
                arr = np.asarray(rows, dtype=np.float32)
                if arr.ndim == 1: arr = arr[None, :]
                self._dbg(f"[prime samples] {arr.shape}")
                return arr, ts_list
            self._dbg("[read_anything] no data")
            return None, []

        def _run():
            try:
                _hb("run enter")

                inlet = None
                if info_obj is not None:
                    try:
                        inlet = lsl.StreamInlet(info_obj, max_buflen=10)
                        try: inlet.open_stream(1.0)
                        except Exception: pass
                        self.on_info({"source": "lsl", "status": "connected"})
                        _hb("inlet from UI ok")
                    except Exception as e:
                        self._dbg(f"inlet UI failed: {e}")
                        inlet = None

                if inlet is None:
                    self.on_info({"source": "lsl", "status": "searching"})
                    picked = _pick_best_stream()
                    if picked is None:
                        self.on_info({"source":"lsl","error":"Aucun flux LSL trouvé (4s)."})
                        return
                    try:
                        inlet = lsl.StreamInlet(picked, max_buflen=10)
                        try: inlet.open_stream(1.0)
                        except Exception: pass
                        self.on_info({"source": "lsl", "status": "connected"})
                        _hb("inlet from scan ok")
                    except Exception as e:
                        self.on_info({"source":"lsl","error":f"Échec ouverture flux: {e}"})
                        return

                # -------- BOOT : lire d'abord quelque chose --------
                boot_deadline = time.monotonic() + 6.0
                got = None; ts_buf: List[float] = []
                while not self._stop.is_set():
                    arr, ts = _read_anything(inlet)
                    if arr is None:
                        if time.monotonic() > boot_deadline:
                            self.on_info({"source":"lsl","error":"Aucun échantillon reçu (6s). Vérifie l'émetteur."})
                            return
                        time.sleep(0.1)
                        continue
                    got = arr
                    if ts: ts_buf.extend(ts[-min(16, len(ts)):])
                    break

                if got is None:
                    self.on_info({"source":"lsl","error":"Lecture initiale impossible."})
                    return

                n_meas = int(got.shape[1]) if got.ndim == 2 else 0
                labels: List[str] = []
                n0, sf0 = n_meas, 0.0
                try:
                    inf = inlet.info()
                    try: sf0 = float(inf.nominal_srate() or 0.0)
                    except Exception: sf0 = 0.0
                    try:
                        chans = inf.desc().child("channels")
                        ch = chans.child("channel")
                        while ch:
                            lab = ch.child_value("label") or f"Ch{len(labels)+1}"
                            labels.append(lab)
                            ch = ch.next_sibling()
                    except Exception:
                        labels = []
                except Exception as e:
                    self._dbg(f"info() failed: {e}")

                if n0 <= 0: n0 = n_meas if n_meas > 0 else (int(self.cfg.get("hint_n_ch") or 0) or 1)
                if sf0 <= 0:
                    if len(ts_buf) >= 5:
                        dt = np.diff(sorted(ts_buf[-6:]))
                        dt = dt[np.isfinite(dt)]
                        if dt.size:
                            med = float(np.median(dt))
                            if med > 0: sf0 = float(1.0/med)
                    if sf0 <= 0: sf0 = float(self.cfg.get("hint_sfreq") or 250.0)

                self._sfreq = float(sf0)
                self._ch_names = (labels[:n0] if labels and len(labels) >= n0 else [f"Ch{i+1}" for i in range(n0)])
                self._prepare_segmenter()
                self._emit_info("lsl", reset=True)

                # adapter le 1er lot puis pousser
                n_eff = len(self._ch_names)
                arr0 = got
                if n_eff > 0 and arr0.shape[1] != n_eff:
                    if arr0.shape[1] < n_eff:
                        pad = np.zeros((arr0.shape[0], n_eff - arr0.shape[1]), dtype=arr0.dtype)
                        arr0 = np.hstack([arr0, pad])
                    else:
                        arr0 = arr0[:, :n_eff]
                self._feed_samples(arr0)

                # -------- boucle continue --------
                while not self._stop.is_set():
                    arr, ts = _read_anything(inlet)
                    if arr is None:
                        time.sleep(0.05); continue

                    n_meas = int(arr.shape[1])
                    if n_meas != len(self._ch_names) and n_meas > 0:
                        self._ch_names = [f"Ch{i+1}" for i in range(n_meas)]
                        self._prepare_segmenter()
                        self._emit_info("lsl", reset=True)

                    n_eff = len(self._ch_names)
                    if n_eff > 0 and arr.shape[1] != n_eff:
                        if arr.shape[1] < n_eff:
                            pad = np.zeros((arr.shape[0], n_eff - arr.shape[1]), dtype=arr.dtype)
                            arr = np.hstack([arr, pad])
                        else:
                            arr = arr[:, :n_eff]

                    self._feed_samples(arr)

            except Exception as e:
                self.on_info({"source":"lsl","error":str(e)})

        self._stop.clear()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()


# ---------------- Émulateur ----------------

class EmulatorDriver(_BaseDriver):
    def start(self):
        sf = int(self.cfg.get("sfreq", 250))
        ch_names = self.cfg.get("ch_names")
        if ch_names:
            ch_names = list(ch_names); n_ch = len(ch_names)
        else:
            n_ch = int(self.cfg.get("n_channels", 8))
            ch_names = [f"Ch{i+1}" for i in range(n_ch)]
        chunk = int(self.cfg.get("chunk", 64))
        noise = float(self.cfg.get("noise", 0.05))

        self._sfreq = float(sf)
        self._ch_names = ch_names
        self._prepare_segmenter()
        self._emit_info("emulator", reset=True)

        def _run():
            t = 0
            while not self._stop.is_set():
                tt = (t + np.arange(chunk)) / sf
                sig = (0.7*np.sin(2*np.pi*10.0*tt)[:, None] + 0.3*np.sin(2*np.pi*20.0*tt)[:, None])
                sig = np.repeat(sig, n_ch, axis=1)
                sig += noise * np.random.randn(chunk, n_ch)
                self._feed_samples(sig.astype(np.float32))
                t += chunk
                time.sleep(0.2 * chunk / sf)

        self._stop.clear()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
