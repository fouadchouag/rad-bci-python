"""
run_ten_runs.py
===============

Orchestrate 10 consecutive benchmark runs for a single (platform, workflow)
combination. Between runs: 15-second cooldown. Total time: ~15-17 min for
10 × 60s runs.

Prerequisites (must be active BEFORE launching this script):
  - The platform under test (RBciAD or OpenViBE) is running with the
    correct W1 or W2 pipeline ACTIVE (connected, streaming).
  - You know the process name or PID to monitor for CPU/RSS.

The script loops:
  for i in 1..10:
      launch sim_eeg_lsl.py (source)
      launch lsl_latency_probe.py (probe)
      launch external_benchmark.py (CPU/RSS)
      wait duration seconds
      stop all three helpers
      cooldown 15 seconds
  end

Logs are written to runs/{PLATFORM}/{WORKFLOW}/latency_run{i}.csv and
runs/{PLATFORM}/{WORKFLOW}/cpu_run{i}.csv

Usage:
    python run_ten_runs.py --platform OpenViBE --workflow W1 \\
        --platform-name openvibe-designer.exe

    python run_ten_runs.py --platform RBciAD --workflow W1 \\
        --platform-name python.exe

    # Resume from run N (if you had to interrupt):
    python run_ten_runs.py --platform OpenViBE --workflow W1 \\
        --platform-name openvibe-designer.exe --start 4
"""

import argparse
import os
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True,
                        choices=["RBciAD", "OpenViBE"])
    parser.add_argument("--workflow", required=True, choices=["W1", "W2"])
    parser.add_argument("--platform-name",
                        help="Process name for CPU/RSS (e.g. python.exe, "
                             "openvibe-designer.exe).")
    parser.add_argument("--platform-pid", type=int,
                        help="PID of platform process (alternative).")
    parser.add_argument("--duration", type=float, default=70.0,
                        help="Duration per run (default 70s: 10 warmup + 60 meas).")
    parser.add_argument("--cooldown", type=float, default=15.0,
                        help="Cooldown between runs (default 15s).")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from run index (default 1; use for resuming).")
    parser.add_argument("--end", type=int, default=10,
                        help="End run index inclusive (default 10).")
    parser.add_argument("--runs-root", default="runs")
    args = parser.parse_args()

    if args.platform_name is None and args.platform_pid is None:
        defaults = {"RBciAD": "python.exe",
                    "OpenViBE": "openvibe-designer.exe"}
        args.platform_name = defaults[args.platform]
        print(f"[runner] Using default process name "
              f"'{args.platform_name}' for {args.platform}")

    out_dir = os.path.join(args.runs_root, args.platform, args.workflow)
    os.makedirs(out_dir, exist_ok=True)

    py = sys.executable
    script_dir = os.path.dirname(os.path.abspath(__file__))

    total = args.end - args.start + 1
    print(f"\n{'='*60}")
    print(f"Starting {total} runs: {args.platform} {args.workflow} "
          f"run #{args.start} to #{args.end}")
    print(f"Output dir: {out_dir}")
    print(f"Duration per run: {args.duration}s  "
          f"Cooldown: {args.cooldown}s")
    est_minutes = (args.duration + args.cooldown + 3) * total / 60.0
    print(f"Estimated total time: {est_minutes:.1f} minutes")
    print(f"{'='*60}\n")

    print("⚠️  IMPORTANT: make sure the platform's pipeline is ACTIVE "
          "(not just open).")
    print("   - RBciAD: Inlet connected, Outlet 'streaming BenchmarkOutput'")
    print("   - OpenViBE: Acquisition Server Playing, Designer Playing")
    print("\nPress Enter to start, or Ctrl+C to abort...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n[runner] Aborted before starting.")
        return

    for i in range(args.start, args.end + 1):
        print(f"\n{'='*60}")
        print(f"RUN {i}/{args.end}  ({args.platform} {args.workflow})")
        print(f"{'='*60}")

        lat_csv = os.path.join(out_dir, f"latency_run{i}.csv")
        cpu_csv = os.path.join(out_dir, f"cpu_run{i}.csv")

        # Safety: skip if both files already exist
        if os.path.exists(lat_csv) and os.path.exists(cpu_csv):
            print(f"[runner] SKIP: {lat_csv} and {cpu_csv} already exist.")
            continue

        # --- Launch source ---
        src_cmd = [py, os.path.join(script_dir, "sim_eeg_lsl.py"),
                   "--duration", str(args.duration)]
        print(f"[runner] Starting source...")
        src = subprocess.Popen(src_cmd, cwd=script_dir)
        time.sleep(3.0)

        # --- Launch CPU/RSS sampler ---
        cpu_cmd = [py, os.path.join(script_dir, "external_benchmark.py"),
                   "--out", os.path.abspath(cpu_csv),
                   "--duration", str(args.duration - 3),
                   "--warmup", "5"]
        if args.platform_pid is not None:
            cpu_cmd += ["--pid", str(args.platform_pid)]
        else:
            cpu_cmd += ["--name", args.platform_name]
        cpu_proc = subprocess.Popen(cpu_cmd, cwd=script_dir)

        # --- Launch latency probe ---
        probe_cmd = [py, os.path.join(script_dir, "lsl_latency_probe.py"),
                     "--out", os.path.abspath(lat_csv),
                     "--duration", str(args.duration - 3)]
        probe_proc = subprocess.Popen(probe_cmd, cwd=script_dir)

        print(f"[runner] Source+probe+CPU sampler all running. "
              f"Waiting {args.duration:.0f}s...")

        try:
            src.wait(timeout=args.duration + 15)
        except subprocess.TimeoutExpired:
            print(f"[runner] WARN: source did not end in time; killing.")
            src.kill()
        except KeyboardInterrupt:
            print(f"\n[runner] Interrupted. Cleaning up this run...")
            for p in [src, cpu_proc, probe_proc]:
                try:
                    p.kill()
                except Exception:
                    pass
            print(f"[runner] To resume later: --start {i}")
            return

        # Let probe and cpu finish flushing
        for p, label in [(probe_proc, "probe"), (cpu_proc, "cpu")]:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(f"[runner] {label} did not finish in time; killing.")
                p.kill()

        # Verify CSVs were written
        lat_ok = os.path.exists(lat_csv) and os.path.getsize(lat_csv) > 50
        cpu_ok = os.path.exists(cpu_csv) and os.path.getsize(cpu_csv) > 50
        status = "OK" if (lat_ok and cpu_ok) else "WARN"
        print(f"[runner] Run {i}: latency={'OK' if lat_ok else 'MISSING'}, "
              f"cpu={'OK' if cpu_ok else 'MISSING'}  -> {status}")

        if i < args.end:
            print(f"[runner] Cooldown {args.cooldown}s before next run...")
            try:
                time.sleep(args.cooldown)
            except KeyboardInterrupt:
                print(f"\n[runner] Interrupted during cooldown. "
                      f"To resume: --start {i+1}")
                return

    print(f"\n{'='*60}")
    print(f"ALL {total} RUNS COMPLETE: {args.platform} {args.workflow}")
    print(f"Output: {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
