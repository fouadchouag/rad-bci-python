import csv, os, time, threading, queue

def now_ns():
    return time.perf_counter_ns()

class BenchLogger:
    def __init__(self, out_dir="logs"):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self._q = queue.Queue(maxsize=10000)
        self._t = None
        self._stop = threading.Event()
        self._first_frame_written_for_run = False
        self.path = None

    def start(self, run_label="run", source="EDF", sr_hz=200.0):
        self._stop.clear()
        self._first_frame_written_for_run = False
        ts = int(time.time())
        self.path = os.path.join(self.out_dir, f"{run_label}_{ts}.csv")
        self._fh = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._fh)
        self._w.writerow(["ts_us","event","payload"])
        self.log("RUN", f"label={run_label},source={source},sr={sr_hz}")
        self._t = threading.Thread(target=self._writer, daemon=True)
        self._t.start()

    def stop(self):
        if not hasattr(self, "_fh"): return
        self._stop.set()
        self._q.put(None)
        if self._t: self._t.join(timeout=1.0)
        self._fh.flush(); self._fh.close()

    def log(self, event: str, payload: str=""):
        ts_us = now_ns() // 1000
        try:
            self._q.put_nowait((ts_us, event, payload))
        except queue.Full:
            pass

    def _writer(self):
        while not self._stop.is_set():
            item = self._q.get()
            if item is None: break
            self._w.writerow(item); self._fh.flush()
