# core/rt_perf.py
# -*- coding: utf-8 -*-
import os, threading
from contextlib import contextmanager
from PyQt5.QtCore import QTimer

# ---------- BLAS threads ----------
def init_fast_defaults(blas_threads: int = 1):
    """À appeler tôt (MainWindow) pour éviter l'over-subscription."""
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(k, str(blas_threads))

def limit_blas_threads():
    """Compat: alias historique (équivalent à init_fast_defaults(1))."""
    init_fast_defaults(blas_threads=1)

# threadpoolctl (optionnel) pour limiter les threads BLAS à la volée
try:
    from threadpoolctl import threadpool_limits
    _TP_OK = True
except Exception:
    _TP_OK = False

@contextmanager
def blas_limits(n_threads: int = 1):
    """Limite temporairement les threads BLAS (MKL/OpenBLAS/BLIS)."""
    if _TP_OK:
        with threadpool_limits(limits=n_threads):
            yield
    else:
        yield

# ---------- Joblib backend (processus, pas de GIL) ----------
try:
    from joblib import parallel_backend
    _JB_OK = True
except Exception:
    _JB_OK = False

@contextmanager
def joblib_loky(n_jobs: int = -1):
    """Active le backend joblib 'loky' (process-based)."""
    if _JB_OK:
        with parallel_backend('loky', n_jobs=n_jobs):
            yield
    else:
        yield

# ---------- Utilitaires temps-réel déjà existants ----------
class DropOldQueue:
    """Queue taille 1: garde seulement la dernière donnée (backpressure drop)."""
    def __init__(self): 
        self._lock = threading.Lock()
        self._item = None
    def put(self, x):
        with self._lock:
            self._item = x
    def get_nowait(self):
        with self._lock:
            x = self._item
            self._item = None
            return x

def start_qtimer(interval_ms, callback, parent=None):
    t = QTimer(parent); t.setInterval(int(interval_ms)); t.timeout.connect(callback); t.start()
    return t
