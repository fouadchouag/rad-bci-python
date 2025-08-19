# tools/lsl_mat_streamer.py
# -*- coding: utf-8 -*-
"""
MAT → LSL streamer
Lit un .mat (BBCI cnt/nfo ou BCI Comp X) et publie un flux LSL de type 'EEG'.

Dépendances:
    pip install numpy pylsl scipy h5py

Exemples:
    # Auto-détection, boucle, chunk 50, publier en Volts
    python tools/lsl_mat_streamer.py --file dataset.mat --mode auto --chunk 50 --loop --units V --scale 1e-6 --name LSLMat

    # Forcer trials, sans conversion (déjà en V), nom explicite
    python tools/lsl_mat_streamer.py --file dataset.mat --mode trials --name "LSLMat Trials"

Notes:
- --units est écrit dans les métadonnées LSL (V ou uV)
- --scale applique un facteur aux données (ex: 1e-6 pour µV→V)
"""

import argparse
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# LSL
try:
    from pylsl import StreamInfo, StreamOutlet, cf_float32
except Exception:
    print("[LSLMAT] ERREUR: pylsl non disponible. Installez: pip install pylsl")
    raise

# MAT loaders
try:
    from scipy.io import loadmat as _scipy_loadmat
except Exception:
    _scipy_loadmat = None

try:
    import h5py as _h5py
except Exception:
    _h5py = None


# -------- Helpers: lecture MAT --------
def _safe_to_list(obj) -> List[str]:
    if obj is None:
        return []
    if isinstance(obj, (list, tuple)):
        out = []
        for x in obj:
            if isinstance(x, bytes):
                out.append(x.decode("utf-8", "ignore"))
            elif isinstance(x, str):
                out.append(x)
            else:
                try:
                    out.append(str(x))
                except Exception:
                    pass
        return out
    arr = np.asarray(obj)
    if arr.dtype.kind in ("U", "S", "O"):
        try:
            return [str(x if not isinstance(x, bytes) else x.decode("utf-8", "ignore")) for x in arr.ravel().tolist()]
        except Exception:
            pass
    try:
        return [str(obj)]
    except Exception:
        return []


def _try_load_scipy(path: str) -> Optional[Dict[str, Any]]:
    if _scipy_loadmat is None:
        return None
    try:
        d = _scipy_loadmat(path, squeeze_me=True, struct_as_record=False)
        return {k: v for k, v in d.items() if not k.startswith("__")}
    except NotImplementedError:
        return None   # v7.3 HDF5
    except Exception:
        return None


def _try_load_h5(path: str) -> Optional[Dict[str, Any]]:
    if _h5py is None:
        return None
    try:
        out: Dict[str, Any] = {}
        with _h5py.File(path, "r") as h5:
            for k in h5.keys():
                out[k] = h5[k]
        return out
    except Exception:
        return None


def _h5_read_nfo(h5_nfo) -> Tuple[Optional[float], List[str]]:
    fs = None
    clab = []
    if not (_h5py and isinstance(h5_nfo, _h5py.Group)):
        return fs, clab
    for key in ("fs", "Fs", "srate"):
        if key in h5_nfo:
            try:
                fs = float(np.array(h5_nfo[key][()]).squeeze())
                break
            except Exception:
                pass
    if "clab" in h5_nfo:
        node = h5_nfo["clab"]
        try:
            if isinstance(node, _h5py.Dataset):
                clab = _safe_to_list(node[()])
            else:
                tmp = []
                for k in node.keys():
                    tmp.extend(_safe_to_list(node[k][()]))
                clab = tmp
        except Exception:
            pass
    return fs, clab


def _auto_channels(n: int) -> List[str]:
    return [f"Ch{i+1}" for i in range(int(max(0, n)))]


def load_mat_for_stream(path: str) -> Tuple[str, float, List[str], Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Retourne:
      style: "bbci-continuous" | "trials-3d" | "continuous-2d"
      sfreq: float
      ch_names: list[str]
      cnt: (n_samples, n_ch) ou None
      trials: (n_trials, n_samples, n_ch) ou None
    """
    d = _try_load_scipy(path)
    if d is None:
        d = _try_load_h5(path)
    if d is None:
        raise RuntimeError("Impossible de lire .mat (scipy/h5py indisponible ou format non supporté)")

    # BBCI continu
    if "cnt" in d:
        if _h5py and isinstance(d["cnt"], _h5py.Dataset):
            cnt = np.array(d["cnt"][()])
        else:
            cnt = np.array(d["cnt"])
        if cnt.ndim == 1:
            cnt = cnt[:, None]
        # (n_samples, n_ch)
        if cnt.shape[0] < cnt.shape[1]:
            # transpose probable si (n_ch, n_samples)
            cnt = cnt.T

        sf = None; clab = []
        nfo = d.get("nfo", None)
        if _h5py and isinstance(nfo, _h5py.Group):
            sf, clab = _h5_read_nfo(nfo)
        elif nfo is not None:
            try:
                sf = float(np.array(getattr(nfo, "fs", None)).squeeze())
            except Exception:
                for k in ("Fs", "srate", "SF", "sf"):
                    try:
                        sf = float(np.array(getattr(nfo, k, None)).squeeze()); break
                    except Exception:
                        pass
            try:
                clab = _safe_to_list(getattr(nfo, "clab", []))
            except Exception:
                pass

        if not sf:
            for k in ("fs", "Fs", "srate"):
                if k in d:
                    try:
                        node = d[k]
                        sf = float(np.array(node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node).squeeze())
                        break
                    except Exception:
                        pass
        if not sf:
            sf = 250.0
        if not clab or len(clab) != cnt.shape[1]:
            clab = _auto_channels(cnt.shape[1])
        return "bbci-continuous", float(sf), list(clab), cnt.astype(np.float64, copy=False), None

    # Trials / autres
    X = None
    for key in ("X", "x", "data", "signals"):
        if key in d:
            try:
                node = d[key]
                X = node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node
                X = np.array(X)
                break
            except Exception:
                pass
    if X is None:
        raise RuntimeError("Format .mat inconnu (ni 'cnt' ni 'X').")

    if X.ndim == 2:
        # (samples, ch) ou (ch, samples)
        cnt = np.array(X)
        if cnt.shape[0] < cnt.shape[1]:
            cnt = cnt.T
        # sf
        sf = None
        for k in ("fs", "Fs", "srate"):
            if k in d:
                try:
                    node = d[k]
                    sf = float(np.array(node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node).squeeze())
                    break
                except Exception:
                    pass
        if not sf:
            sf = 250.0
        ch_names = _auto_channels(cnt.shape[1])
        return "continuous-2d", float(sf), ch_names, cnt.astype(np.float64, copy=False), None

    if X.ndim == 3:
        arr = np.array(X)
        shape = arr.shape
        # Détecter axes: channels = dimension 8..512, samples = la plus grande
        ch_axis = max(range(3), key=lambda i: (8 <= shape[i] <= 512, shape[i]))
        smp_axis = max(range(3), key=lambda i: shape[i])
        axes = [0, 1, 2]; axes.remove(ch_axis); axes.remove(smp_axis)
        tr_axis = axes[0]
        arr = np.moveaxis(arr, [tr_axis, smp_axis, ch_axis], [0, 1, 2])  # (T, S, C)

        sf = None
        for k in ("fs", "Fs", "srate"):
            if k in d:
                try:
                    node = d[k]
                    sf = float(np.array(node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node).squeeze())
                    break
                except Exception:
                    pass
        if not sf:
            sf = 250.0

        ch_names = None
        for k in ("chanlocs", "channels", "clab", "ch_names"):
            if k in d:
                try:
                    node = d[k]
                    if _h5py and isinstance(node, (_h5py.Dataset, _h5py.Group)):
                        try:
                            val = node[()] if isinstance(node, _h5py.Dataset) else node
                        except Exception:
                            val = None
                        ch_names = _safe_to_list(val)
                    else:
                        ch_names = _safe_to_list(node)
                    break
                except Exception:
                    pass
        if not ch_names or len(ch_names) != arr.shape[2]:
            ch_names = _auto_channels(arr.shape[2])
        return "trials-3d", float(sf), list(ch_names), None, arr.astype(np.float64, copy=False)

    raise RuntimeError(f"Forme non supportée: {X.shape}")


# -------- LSL Info --------
def build_info(name: str, nch: int, sf: float, sid: str, ch_names: List[str], units: str, meta: Dict[str, Any]) -> StreamInfo:
    info = StreamInfo(name=name, type="EEG", channel_count=nch, nominal_srate=sf, channel_format=cf_float32, source_id=sid)
    desc = info.desc()
    desc.append_child_value("manufacturer", "LSLMAT")
    dev = desc.append_child("device")
    for k, v in meta.items():
        dev.append_child_value(str(k), str(v))
    chs = desc.append_child("channels")
    for lab in ch_names:
        ch = chs.append_child("channel")
        ch.append_child_value("label", lab)
        ch.append_child_value("unit", units)
        ch.append_child_value("type", "EEG")
    return info


# -------- Main --------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help=".mat path")
    ap.add_argument("--mode", choices=["auto", "continuous", "trials"], default="auto", help="auto détecte, sinon forcer")
    ap.add_argument("--chunk", type=int, default=50, help="taille des paquets envoyés (samples)")
    ap.add_argument("--loop", action="store_true", help="boucler la lecture")
    ap.add_argument("--name", type=str, default="", help="Nom LSL (défaut: LSLMat-<basename>)")
    ap.add_argument("--source-id", type=str, default="", help="Source ID LSL (défaut: lslmat-<uuid8>)")
    ap.add_argument("--units", type=str, default="V", choices=["V","uV"], help="Unités à déclarer dans LSL")
    ap.add_argument("--scale", type=float, default=1.0, help="Facteur à appliquer aux données (ex: 1e-6 pour µV→V)")
    args = ap.parse_args()

    path = args.file
    if not os.path.isfile(path):
        raise SystemExit(f"Fichier introuvable: {path}")

    style, sf, ch_names, cnt, trials = load_mat_for_stream(path)
    print(f"[LSLMAT] Loaded: style={style} sf={sf}Hz nch={len(ch_names)}")

    # Choix mode
    mode = args.mode
    if mode == "auto":
        mode = "trials" if trials is not None else "continuous"
    print(f"[LSLMAT] Mode: {mode}")

    name = args.name.strip() or f"LSLMat-{os.path.splitext(os.path.basename(path))[0]}"
    sid = args.source_id.strip() or f"lslmat-{uuid.uuid4().hex[:8]}"
    units = args.units
    scale = float(args.scale or 1.0)

    nch = len(ch_names)
    info = build_info(
        name=name,
        nch=nch,
        sf=sf,
        sid=sid,
        ch_names=ch_names,
        units=units,
        meta={"file": os.path.basename(path), "style": style, "mode": mode}
    )
    outlet = StreamOutlet(info, chunk_size=args.chunk, max_buffered=360)
    print(f"[LSLMAT] Publishing LSL: {name}/EEG — {nch}ch @{sf:.1f}Hz (sid={sid}) units={units} chunk={args.chunk}")

    try:
        if mode == "continuous":
            if cnt is None:
                # concaténation trials -> continu
                T, S, C = trials.shape
                cnt = trials.reshape(T*S, C)
            idx = 0
            N = cnt.shape[0]
            while True:
                if idx >= N:
                    if args.loop:
                        idx = 0
                    else:
                        break
                end = min(idx + args.chunk, N)
                block = cnt[idx:end, :]
                idx = end
                if scale != 1.0:
                    block = block * scale
                outlet.push_chunk(block.astype(np.float32, copy=False).tolist())
                # pacing
                dur = block.shape[0] / float(sf) if sf > 0 else 0.004
                time.sleep(max(0.0005, dur))
        else:
            # trials
            T, S, C = trials.shape
            for t in range(T):
                k = 0
                while k < S:
                    end = min(k + args.chunk, S)
                    block = trials[t, k:end, :]
                    k = end
                    if scale != 1.0:
                        block = block * scale
                    outlet.push_chunk(block.astype(np.float32, copy=False).tolist())
                    dur = block.shape[0] / float(sf) if sf > 0 else 0.004
                    time.sleep(max(0.0005, dur))
                # petite pause entre essais (facultatif)
                time.sleep(0.05)
            if args.loop:
                # reboucler
                print("[LSLMAT] Looping…")
                return main()  # relance simple
    except KeyboardInterrupt:
        print("\n[LSLMAT] Stopped by user.")
    except Exception as e:
        print(f"[LSLMAT] ERROR: {e}")
    finally:
        print("[LSLMAT] Bye.")
        

if __name__ == "__main__":
    main()
