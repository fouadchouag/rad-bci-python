# utils/eval_log.py
# -*- coding: utf-8 -*-
"""
Petite API de logging pour les benchs RBciAD.

- Écrit des lignes CSV: ts,EVT,payload
- ts par défaut en nanosecondes (ns) -> compatible avec tes logs existants
- Aucune ligne d'en-tête (parseur existant OK)
- Thread-safe; auto-création du dossier logs/

Événements typiques:
  START_TTFP
  FIRST_FRAME[,frame_id=...]
  FRAME[,n=...]
  FRAMES_STAT,"<rendered>,<expected>"
  PARAM_CHANGE,<k>=<v> [<k>=<v> ...]
  SAMPLES_IN,<total_samples>
  RUN,<key>=<val> [...]

Intégration minimale:
  - MainWindow: log_evt("START_TTFP")  # déjà fait (bouton / F9)
  - EEGLiveDisplay: à chaque rendu => log_frame(n=...) ; et 1x FIRST_FRAME auto après START_TTFP
  - AcquisitionManager: après ajout d’échantillons => log_samples_in(total)
"""

import os, time, threading, datetime

# ---------- état global ----------
_lock = threading.Lock()
_fh = None
_log_path = None
_unit = "ns"  # 'ns' par défaut
_first_pending = False   # après START_TTFP: attendre FIRST_FRAME
_first_logged = False
_frames_rendered = 0
_frames_expected = 0

def _now_val():
    t_ns = time.time_ns()
    if _unit == "ns":
        return t_ns
    elif _unit == "us":
        return t_ns // 1_000
    elif _unit == "ms":
        return t_ns // 1_000_000
    else:
        return t_ns  # fallback

def _open_if_needed():
    global _fh, _log_path
    if _fh is not None:
        return
    os.makedirs("logs", exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_path = os.path.join("logs", f"run_{stamp}.csv")
    _fh = open(_log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    # Petite ligne META (facultative et ignorée par tes scripts)
    _fh.write(f"{_now_val()},META,unit={_unit} version=1\n")

def init_log(path: str = None, unit: str = "ns", append: bool = True):
    """Optionnel: forcer un chemin et/ou l’unité ('ns'|'us'|'ms')."""
    global _fh, _log_path, _unit
    with _lock:
        if _fh is not None:
            _fh.flush()
            _fh.close()
            _fh = None
        _unit = unit.lower().strip()
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            _log_path = path
            _fh = open(_log_path, "a" if append else "w", encoding="utf-8", buffering=1)
            _fh.write(f"{_now_val()},META,unit={_unit} version=1\n")

def close_log():
    global _fh
    with _lock:
        if _fh:
            _fh.flush()
            _fh.close()
            _fh = None

def get_log_path():
    return _log_path

def _write(ev: str, payload: str = ""):
    _open_if_needed()
    ts = _now_val()
    line = f"{ts},{ev},{payload}\n" if payload else f"{ts},{ev},\n"
    _fh.write(line)

# ---------- API publique ----------
def log_evt(ev: str, payload: str = "", **kv):
    """Écrit un événement brut. Si ev == START_TTFP, arme l’attente de FIRST_FRAME."""
    global _first_pending, _first_logged
    with _lock:
        if kv and not payload:
            # payload "k=v k2=v2" (simple et lisible)
            payload = " ".join(f"{k}={v}" for k, v in kv.items())
        _write(ev, payload)
        if ev == "START_TTFP":
            _first_pending = True
            _first_logged = False

def log_start_ttfp():
    log_evt("START_TTFP")

def log_param_change(**params):
    # Exemple: log_param_change(win_s=10.0, overlap_pct=50)
    parts = []
    for k, v in params.items():
        parts.append(f"{k}={v}")
    log_evt("PARAM_CHANGE", " ".join(parts))

def log_frame(n: int = None):
    """Log FRAME; si un START_TTFP vient d’avoir lieu, FIRST_FRAME est loggé une seule fois avant."""
    global _first_pending, _first_logged, _frames_rendered
    with _lock:
        if _first_pending and not _first_logged:
            # FIRST_FRAME en priorité
            _write("FIRST_FRAME", f"frame_id={n}" if n is not None else "")
            _first_logged = True
            _first_pending = False
        _frames_rendered += 1
        _write("FRAME", f"n={n}" if n is not None else "")

def log_frames_stat(rendered: int, expected: int):
    """Statistiques cumulées sur les frames (pour le % de drop)."""
    global _frames_rendered, _frames_expected
    with _lock:
        _frames_rendered = int(rendered)
        _frames_expected = int(expected)
        # payload entre guillemets pour être identique à tes logs: "r,e"
        _write("FRAMES_STAT", f"\"{_frames_rendered},{_frames_expected}\"")

def bump_expected_frames(delta: int = 1):
    """Si tu connais le nombre de frames 'attendues' (par ex. cadence d’update),
    appelle ça pour que FRAMES_STAT reflète d’éventuels drops."""
    global _frames_expected
    with _lock:
        _frames_expected += int(delta)

def log_samples_in(total_samples: int):
    _write("SAMPLES_IN", str(int(total_samples)))

def log_run(**tags):
    """Étiquette libre: source=lsl / scenario=W3 etc."""
    if not tags:
        _write("RUN", "")
    else:
        _write("RUN", " ".join(f"{k}={v}" for k, v in tags.items()))
