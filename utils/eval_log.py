# utils/eval_log.py
import time, csv, os

LOG_DIR = "eval"
LOG_PATH = os.path.join(LOG_DIR, "eval_log.csv")
os.makedirs(LOG_DIR, exist_ok=True)

def log_evt(name: str, meta: str = ""):
    """Écrit une ligne: timestamp_ns, event, meta -> eval/eval_log.csv"""
    t_ns = time.perf_counter_ns()
    with open(LOG_PATH, "a", newline="") as f:
        csv.writer(f).writerow([t_ns, name, meta])
