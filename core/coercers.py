# core/coercers.py
# -*- coding: utf-8 -*-
import numpy as np

# ---------- EEG / segment ----------
def coerce_segment(x):
    """Coerce vers ndarray float32 2D (n_ch, n_samples), copie minimale."""
    if x is None:
        return None
    arr = np.asarray(x)
    if arr.ndim == 1:
        arr = arr[np.newaxis, :]
    # matérialiser si memmap
    if isinstance(arr.base, np.memmap):
        arr = np.array(arr, copy=True)
    # dtype
    if arr.dtype != np.float32:
        arr = arr.astype(np.float32, copy=False)
    # NaN/Inf → num (évitent crash UI)
    if not np.isfinite(arr).all():
        arr = np.nan_to_num(arr, copy=False)
    # contigu
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr

def is_segment_like(x):
    if x is None:
        return True  # inconnu au branchement → OK
    try:
        arr = np.asarray(x)
    except Exception:
        return False
    return arr.ndim in (1, 2) and arr.size > 0

# ---------- Registre ----------
_FAMILY_COERCERS = {
    "segment": coerce_segment,
    "eeg.segment": coerce_segment,
}
_FAMILY_VALIDATORS = {
    "segment": is_segment_like,
    "eeg.segment": is_segment_like,
}

def coerce_for_family(fam):
    return _FAMILY_COERCERS.get(fam, lambda v: v)

def is_value_compatible(fam, v):
    return _FAMILY_VALIDATORS.get(fam, lambda _v: True)(v)
