"""
run_benchmark_session.py
========================

Orchestrator that runs ONE benchmark trial end-to-end:
  1. starts sim_eeg_lsl.py (source)
  2. starts lsl_latency_probe.py (probe, --out latency_run{N}.csv)
  3. starts external_benchmark.py (CPU/RSS, --out cpu_run{N}.csv)
  4. waits for the declared duration
  5. shuts everything down cleanly

It does NOT start the platform under test (RBciAD / OpenViBE /
BCI2000) — you do that manually, *before* calling this script, because
each platform has its own launcher and you need to load the W1/W2
graph in the GUI. The orchestrator only coordinates the three Python
helpers around your already-running platform.

Typical usage:
  1. In one shell, launch RBciAD (or OpenViBE, or BCI2000) and load W2.
     Keep the pipeline PAUSED / not yet started.
  2. Note the PID of the platform process.
  3. Run this script:

        python run_benchmark_session.py \
            --platform RBciAD --workflow W2 --run-idx 3 \
            --platform-pid 12345 \
            --duration 70

  4. When the script says "SOURCE RUNNING", press 'Play' / 'Start' in
     the platform GUI within 2-3 seconds.
  5. Wait for the script to finish and write the CSVs.
"""

import argparse
import os
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Run one benchmark trial.")
    parser.add_argument("--platform", required=True,
                        choices=["RBciAD", "OpenViBE", "BCI2000"])
    parser.add_argument("--workflow", required=True, choices=["W1", "W2"])
    parser.add_argument("--run-idx", required=True, type=int,
                        help="Run index (1..10).")
    parser.add_argument("--platform-pid", type=int,
                        help="PID of the platform process (for CPU/RSS).")
    parser.add_argument("--platform-name", type=str,
                        help="Process name for CPU/RSS "
                             "(alternative to --platform-pid).")
    parser.add_argument("--duration", type=float, default=70.0,
                        help="Total trial duration in seconds (default 70).")
    parser.add_argument("--runs-root", default="runs",
                        help="Root folder for outputs.")
    args = parser.parse_args()

    if args.platform_pid is None and args.platform_name is None:
        # Default name per platform -- adjust if your install differs
        default_names = {
            "RBciAD": "python.exe",
            "OpenViBE": "openvibe-designer.exe",
            "BCI2000": "Operator.exe",
        }
        args.platform_name = default_names[args.platform]
        print(f"[orchestrator] Using default process name "
              f"'{args.platform_name}' for {args.platform}")

    out_dir = os.path.join(args.runs_root, args.platform, args.workflow)
    os.makedirs(out_dir, exist_ok=True)
    lat_csv = os.path.join(out_dir, f"latency_run{args.run_idx}.csv")
    cpu_csv = os.path.join(out_dir, f"cpu_run{args.run_idx}.csv")

    python_exe = sys.executable

    print(f"[orchestrator] Trial: {args.platform} / {args.workflow} / "
          f"run {args.run_idx}")
    print(f"[orchestrator] Output: {lat_csv}, {cpu_csv}")

    # ---- 1. Start source ----
    src_cmd = [python_exe, "sim_eeg_lsl.py", "--duration", str(args.duration)]
    src = subprocess.Popen(src_cmd)
    print(f"[orchestrator] Source started (PID {src.pid}). Sleeping 3 s...")
    time.sleep(3.0)

    print("[orchestrator] === SOURCE RUNNING. "
          "PRESS 'PLAY' IN THE PLATFORM NOW. ===")
    time.sleep(2.0)

    # ---- 2. Start CPU/RSS sampler ----
    cpu_cmd = [python_exe, "external_benchmark.py",
               "--out", cpu_csv,
               "--duration", str(args.duration - 3),
               "--warmup", "5"]
    if args.platform_pid is not None:
        cpu_cmd += ["--pid", str(args.platform_pid)]
    else:
        cpu_cmd += ["--name", args.platform_name]
    cpu_proc = subprocess.Popen(cpu_cmd)
    print(f"[orchestrator] CPU/RSS sampler started (PID {cpu_proc.pid}).")

    # ---- 3. Start latency probe ----
    probe_cmd = [python_exe, "lsl_latency_probe.py",
                 "--out", lat_csv,
                 "--duration", str(args.duration - 3)]
    probe_proc = subprocess.Popen(probe_cmd)
    print(f"[orchestrator] Latency probe started (PID {probe_proc.pid}).")

    # ---- 4. Wait ----
    try:
        src.wait(timeout=args.duration + 10)
    except subprocess.TimeoutExpired:
        print("[orchestrator] Source did not exit in time; killing it.")
        src.kill()

    # ---- 5. Let probe/cpu finish writing ----
    for p, label in [(probe_proc, "probe"), (cpu_proc, "cpu")]:
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print(f"[orchestrator] {label} did not finish in time; killing.")
            p.kill()

    print("[orchestrator] Trial complete.")
    print(f"[orchestrator] Output files: {lat_csv}, {cpu_csv}")
    print("[orchestrator] You can now STOP the platform pipeline.")


if __name__ == "__main__":
    main()
