import os, sys, yaml, subprocess, signal, time
from PyQt5.QtCore import QTimer

class BenchController:
    def __init__(self, mainwin, acquisition_manager, bench_logger, param_applier,
                 bench_plan_path="bench/bench_plan.yaml", ps_logger_script="bench/ps_logger_tree.py"):
        self.ui = mainwin
        self.acq = acquisition_manager
        self.bench = bench_logger
        self.apply = param_applier
        self.plan_path = bench_plan_path
        self.ps_script = ps_logger_script
        with open(self.plan_path, "r", encoding="utf-8") as f:
            plan = yaml.safe_load(f)
        self.profiles = plan["profiles"]
        self.out_dir = plan.get("bench", {}).get("out_dir", "logs")
        os.makedirs(self.out_dir, exist_ok=True)
        self._timers = []
        self._idx = 0
        self._ps_proc = None

    def run_all(self):
        self._idx = 0
        self._run_next()

    def _run_next(self):
        if self._idx >= len(self.profiles):
            return
        prof = self.profiles[self._idx]
        self._run_profile(prof)

    def _run_profile(self, prof):
        label = prof["id"]; source = prof["source"]; sr = float(prof["sr_hz"])
        dur_ms = int(float(prof["duration_s"]) * 1000)
        edits = prof.get("edits", [])

        # start logging & acquisition
        self.bench.start(run_label=label, source=source, sr_hz=sr)
        self.bench.log("START_TTFP","")
        self.acq.prepare(source_cfg=source)   # adapte: chemin EDF/nom stream LSL
        self.acq.start()

        # start host CPU/RAM logger (process + enfants)
        self._start_ps_logger(label)

        # plan edits
        self._timers.clear()
        for ev in edits:
            t = QTimer(self.ui)
            t.setSingleShot(True)
            t.timeout.connect(lambda e=ev: self.apply.apply(e["key"], e["value"]))
            t.start(int(float(ev["t"]) * 1000))
            self._timers.append(t)

        # plan stop
        tstop = QTimer(self.ui)
        tstop.setSingleShot(True)
        tstop.timeout.connect(self._stop_current)
        tstop.start(dur_ms)
        self._timers.append(tstop)

    def _stop_current(self):
        self._stop_ps_logger()
        self.acq.stop()
        self.bench.stop()
        self._idx += 1
        QTimer.singleShot(1000, self._run_next)

    def _start_ps_logger(self, label):
        # log CPU/RAM du process courant (PID de l'app)
        pid = os.getpid()
        out = os.path.join(self.out_dir, f"host_usage_{label}.csv")
        self._ps_proc = subprocess.Popen(
            [sys.executable, self.ps_script, "--pid", str(pid), "--label", label, "--out", out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def _stop_ps_logger(self):
        if self._ps_proc and self._ps_proc.poll() is None:
            try:
                if os.name == "nt":
                    self._ps_proc.terminate()
                else:
                    self._ps_proc.send_signal(signal.SIGINT)
                self._ps_proc.wait(timeout=2.0)
            except Exception:
                self._ps_proc.kill()
        self._ps_proc = None
