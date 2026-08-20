"""
external_benchmark.py
=====================

External CPU and memory sampler for the RBciAD cross-platform benchmark.

Samples a target process (by PID, by executable name, or by window title
pattern) at 10 Hz, and writes a CSV time series of:
    time_s, cpu_percent, rss_mb

Usage examples:
    # Simple: watch by PID
    python external_benchmark.py --pid 12345 --out runs/RBciAD/W2/cpu_run1.csv --duration 70

    # By executable name (matches the first process whose exe name matches)
    python external_benchmark.py --name openvibe-designer.exe --out ... --duration 70
    python external_benchmark.py --name Operator.exe --out ... --duration 70    # BCI2000
    python external_benchmark.py --name python.exe      --out ... --duration 70 # RBciAD

Design notes:
- We sample the target *process* including all its children, to capture
  multi-process architectures (BCI2000 spawns several modules).
- The first cpu_percent() call is a dummy (psutil warm-up requirement).
- If the target disappears mid-run, we record NaN and keep going
  until --duration elapses or we reach the stop sentinel.
"""

import argparse
import csv
import math
import sys
import time

import psutil


SAMPLING_HZ = 10  # 10 Hz -> one sample every 100 ms


def find_process(pid=None, name=None):
    """Return a psutil.Process for the given PID or name, or exit."""
    if pid is not None:
        try:
            return psutil.Process(pid)
        except psutil.NoSuchProcess:
            print(f"[cpu_rss] No process with PID {pid}", file=sys.stderr)
            sys.exit(2)

    if name is not None:
        name_low = name.lower()
        candidates = []
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pname = (p.info.get("name") or "").lower()
                if name_low in pname:
                    candidates.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not candidates:
            print(f"[cpu_rss] No running process matching '{name}'",
                  file=sys.stderr)
            sys.exit(2)
        if len(candidates) > 1:
            print(f"[cpu_rss] WARNING: {len(candidates)} processes match "
                  f"'{name}'. Watching PID {candidates[0].pid}.",
                  file=sys.stderr)
        return candidates[0]

    print("[cpu_rss] Must specify --pid or --name", file=sys.stderr)
    sys.exit(2)


def collect_tree(root_proc):
    """Return [root_proc] + all its children (recursive), live only."""
    procs = [root_proc]
    try:
        procs.extend(root_proc.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    # Filter out any that already died
    return [p for p in procs if p.is_running()]


def sample_tree(procs, n_cpu):
    """
    Sum cpu_percent (normalized to 100%, not n_cpu*100%) and rss_mb
    across the whole process tree.
    """
    cpu_sum = 0.0
    rss_sum = 0
    live = 0
    for p in procs:
        try:
            cpu_sum += p.cpu_percent(interval=None)
            rss_sum += p.memory_info().rss
            live += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if live == 0:
        return (float("nan"), float("nan"))
    # psutil returns cpu% per-CPU-summed (can exceed 100 on SMP).
    # We normalize to "single-CPU-equivalent percent" for cross-machine
    # comparability.
    cpu_norm = cpu_sum / n_cpu
    rss_mb = rss_sum / (1024 * 1024)
    return (cpu_norm, rss_mb)


def main():
    parser = argparse.ArgumentParser(description="Sample CPU% and RSS of a "
                                                 "target process at 10 Hz.")
    parser.add_argument("--pid", type=int,
                        help="Target PID (mutually exclusive with --name).")
    parser.add_argument("--name", type=str,
                        help="Target executable name substring "
                             "(case-insensitive).")
    parser.add_argument("--out", required=True, help="Output CSV path.")
    parser.add_argument("--duration", type=float, default=70.0,
                        help="Sampling duration in seconds (default 70).")
    parser.add_argument("--warmup", type=float, default=10.0,
                        help="Warmup seconds NOT written to CSV (default 10).")
    args = parser.parse_args()

    if (args.pid is None) == (args.name is None):
        print("[cpu_rss] Specify exactly one of --pid or --name.",
              file=sys.stderr)
        sys.exit(2)

    n_cpu = psutil.cpu_count(logical=True) or 1

    root = find_process(pid=args.pid, name=args.name)
    print(f"[cpu_rss] Watching PID {root.pid} ({root.name()}) "
          f"and its children on {n_cpu} logical CPUs.")

    # psutil warm-up: first cpu_percent() call returns 0.0 by design
    procs = collect_tree(root)
    for p in procs:
        try:
            p.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    t_start = time.monotonic()
    t_end = t_start + args.duration
    dt = 1.0 / SAMPLING_HZ

    rows = []
    next_t = t_start
    while True:
        now = time.monotonic()
        if now >= t_end:
            break
        # Re-collect children in case new ones appeared (e.g. BCI2000 modules)
        procs = collect_tree(root)
        if not procs:
            # Root died; record NaN and keep the time slot
            rows.append((now - t_start, float("nan"), float("nan")))
        else:
            cpu, rss = sample_tree(procs, n_cpu)
            rows.append((now - t_start, cpu, rss))

        next_t += dt
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)

    # Drop warm-up period
    rows_kept = [r for r in rows if r[0] >= args.warmup]

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "cpu_percent", "rss_mb"])
        for t, cpu, rss in rows_kept:
            w.writerow([f"{t:.3f}",
                        "nan" if math.isnan(cpu) else f"{cpu:.2f}",
                        "nan" if math.isnan(rss) else f"{rss:.1f}"])

    # Quick stats to console
    cpus = [c for (_, c, _) in rows_kept if not math.isnan(c)]
    rsss = [r for (_, _, r) in rows_kept if not math.isnan(r)]
    if cpus and rsss:
        print(f"[cpu_rss] CPU avg={sum(cpus)/len(cpus):.2f}%  "
              f"max={max(cpus):.2f}%")
        print(f"[cpu_rss] RSS avg={sum(rsss)/len(rsss):.1f} MB  "
              f"max={max(rsss):.1f} MB")
    print(f"[cpu_rss] Wrote {len(rows_kept)} samples to {args.out}")


if __name__ == "__main__":
    main()
