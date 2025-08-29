# core/metrics_logger.py
# -*- coding: utf-8 -*-
import os, csv, time, threading
try:
    import psutil
except Exception:
    psutil = None

__all__ = ["init_metrics_logger", "deinit_metrics_logger", "is_active", "metrics"]

_LOCK = threading.Lock()
_SINGLETON = None


class _Metrics:
    def __init__(self, out_csv):
        self.out_csv = out_csv
        self._stop = False
        self._cpu_thread = None

    def _ts_ns(self):
        return int(time.time_ns())

    def _write(self, kind, payload=""):
        # si on est stoppé, ne plus écrire
        if self._stop:
            return
        with _LOCK:
            with open(self.out_csv, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([self._ts_ns(), kind, payload])

    # ---------------- API publique (événements génériques) ----------------
    def event(self, name, **fields):
        msg = ",".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        self._write(name, msg)

    def log(self, name, **fields):
        msg = ",".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        self._write(name, msg)

    def param_change(self, name, old=None, new=None):
        self._write("PARAM_CHANGE", f"name={name},old={old},new={new}")

    def run_meta(self, **fields):
        self._write("RUN_META", ",".join(f"{k}={v}" for k, v in fields.items()))

    def cpu_mem(self, cpu=None, rss_mb=None):
        self._write("CPU_MEM", f"cpu={cpu},rss_mb={rss_mb}")

    # ---------------- TTFP / Frames ----------------
    def start_ttfp(self):
        self._write("START_TTFP", "")

    # alias compat
    def ttfp(self):
        self.start_ttfp()

    def first_frame(self, **fields):
        msg = ",".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        self._write("FIRST_FRAME", msg)

    def frame_rendered(self, **fields):
        msg = ",".join(f"{k}={v}" for k, v in fields.items()) if fields else ""
        self._write("FRAME_RENDERED", msg)

    # ---------------- CPU/MEM loop ----------------
    def _cpu_loop(self, interval=0.5):
        p = psutil.Process(os.getpid()) if psutil else None
        while not self._stop:
            try:
                if psutil and p:
                    cpu = psutil.cpu_percent(interval=None)
                    rss_mb = int(p.memory_info().rss / (1024 * 1024))
                    self.cpu_mem(cpu=cpu, rss_mb=rss_mb)
                time.sleep(interval)
            except Exception:
                time.sleep(interval)

    def start_cpu_probe(self, interval=0.5):
        if psutil is None or self._cpu_thread is not None:
            return
        self._cpu_thread = threading.Thread(target=self._cpu_loop, args=(interval,), daemon=True)
        self._cpu_thread.start()

    def stop(self):
        # Évite toute écriture ultérieure
        self._stop = True
        # Tente de rejoindre le thread CPU si présent
        th = self._cpu_thread
        self._cpu_thread = None
        if th and th.is_alive():
            try:
                th.join(timeout=1.0)
            except Exception:
                pass


def init_metrics_logger(app_name="RBciAD", out_dir="runs"):
    """
    Crée runs/<timestamp>.csv, démarre le sondage CPU/MEM et expose metrics().
    A appeler via F9 (pas au démarrage de l'app).
    """
    global _SINGLETON
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    fn = os.path.join(out_dir, f"{stamp}.csv")

    m = _Metrics(fn)
    m.run_meta(config="unsaved", mode="GUI", app=app_name)
    m.start_cpu_probe(interval=0.5)

    _SINGLETON = m
    return fn


def deinit_metrics_logger():
    """Stoppe la session active et désactive metrics()."""
    global _SINGLETON
    if _SINGLETON is not None:
        try:
            _SINGLETON.event("RUN_END")
        except Exception:
            pass
        try:
            _SINGLETON.stop()
        except Exception:
            pass
    _SINGLETON = None


def is_active():
    """True si une session de métriques est active (F9 ON)."""
    return _SINGLETON is not None


def metrics():
    global _SINGLETON

    class _Noop:
        def event(self, *a, **k): pass
        def log(self, *a, **k): pass
        def first_frame(self, *a, **k): pass
        def frame_rendered(self, *a, **k): pass
        def param_change(self, *a, **k): pass
        def run_meta(self, *a, **k): pass
        def cpu_mem(self, *a, **k): pass
        def start_ttfp(self, *a, **k): pass
        def ttfp(self, *a, **k): pass
        def stop(self): pass

    return _SINGLETON if _SINGLETON is not None else _Noop()
