"""
aggregate_cross_platform.py
===========================

Aggregate per-run CSV logs into a cross-platform summary for the
RBciAD benchmark.

Expected folder structure:
    runs/
      RBciAD/
        W1/
          latency_run1.csv, cpu_run1.csv, latency_run2.csv, cpu_run2.csv, ...
        W2/
          ...
      OpenViBE/
        W1/ ...
        W2/ ...
      BCI2000/
        W1/ ...
        W2/ ...

For each (platform, workflow) combination, the script reads all pairs
(latency_run*.csv, cpu_run*.csv) and computes:
    - latency_p50_ms, latency_p95_ms   (aggregated over all pulses of all runs)
    - cpu_avg_pct, cpu_max_pct         (median-of-per-run averages / maxes)
    - rss_avg_mb,  rss_max_mb          (same)
    - n_runs, n_pulses

Also runs pairwise Wilcoxon signed-rank tests on the per-run medians,
with Holm-Bonferroni correction.

Outputs:
    summary/cross_platform_summary.csv     (one row per platform x workflow)
    summary/pairwise_tests.csv             (Wilcoxon results)

Usage:
    python aggregate_cross_platform.py --runs-dir runs --out-dir summary
"""

import argparse
import csv
import math
import os
from collections import defaultdict
from statistics import mean, median

try:
    from scipy.stats import wilcoxon
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


PLATFORMS = ["RBciAD", "OpenViBE", "BCI2000"]
WORKFLOWS = ["W1", "W2"]


def pct(sorted_vals, q):
    """Linear-interpolation percentile (q in [0,1])."""
    if not sorted_vals:
        return float("nan")
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def read_latency_csv(path):
    """Return list of latency values in ms from one latency_run*.csv."""
    out = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                v = float(row["latency_ms"])
                if math.isfinite(v) and 0.0 <= v < 5000.0:
                    out.append(v)
            except (KeyError, ValueError):
                continue
    return out


def read_cpu_csv(path):
    """Return (cpu_avg, cpu_max, rss_avg, rss_max) for one cpu_run*.csv."""
    cpus, rsss = [], []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                c = float(row["cpu_percent"])
                rs = float(row["rss_mb"])
                if math.isfinite(c):
                    cpus.append(c)
                if math.isfinite(rs):
                    rsss.append(rs)
            except (KeyError, ValueError):
                continue
    if not cpus or not rsss:
        return (float("nan"),) * 4
    return (mean(cpus), max(cpus), mean(rsss), max(rsss))


def pair_run_files(folder):
    """Return list of (latency_path, cpu_path) pairs for run_i in folder."""
    if not os.path.isdir(folder):
        return []
    files = os.listdir(folder)
    lat = {}
    cpu = {}
    for f in files:
        lower = f.lower()
        # Extract run number from "latency_run3.csv" or "cpu_run3.csv"
        if lower.startswith("latency_run") and lower.endswith(".csv"):
            idx = lower[len("latency_run"):-len(".csv")]
            lat[idx] = os.path.join(folder, f)
        elif lower.startswith("cpu_run") and lower.endswith(".csv"):
            idx = lower[len("cpu_run"):-len(".csv")]
            cpu[idx] = os.path.join(folder, f)
    common = sorted(set(lat.keys()) & set(cpu.keys()),
                    key=lambda x: int(x) if x.isdigit() else 0)
    return [(lat[i], cpu[i]) for i in common]


def aggregate_platform_workflow(runs_dir, platform, workflow):
    folder = os.path.join(runs_dir, platform, workflow)
    pairs = pair_run_files(folder)
    if not pairs:
        return None

    all_latencies = []          # pooled across runs (for overall P50/P95)
    per_run_latency_median = [] # one value per run (for Wilcoxon)
    per_run_cpu_avg = []
    per_run_cpu_max = []
    per_run_rss_avg = []
    per_run_rss_max = []

    for lat_path, cpu_path in pairs:
        lats = read_latency_csv(lat_path)
        if lats:
            lats_sorted = sorted(lats)
            all_latencies.extend(lats)
            per_run_latency_median.append(median(lats_sorted))
        cpu_avg, cpu_max, rss_avg, rss_max = read_cpu_csv(cpu_path)
        if math.isfinite(cpu_avg):
            per_run_cpu_avg.append(cpu_avg)
            per_run_cpu_max.append(cpu_max)
            per_run_rss_avg.append(rss_avg)
            per_run_rss_max.append(rss_max)

    all_latencies.sort()
    return {
        "platform": platform,
        "workflow": workflow,
        "n_runs": len(pairs),
        "n_pulses": len(all_latencies),
        "latency_p50_ms": pct(all_latencies, 0.50),
        "latency_p95_ms": pct(all_latencies, 0.95),
        "cpu_avg_pct": median(per_run_cpu_avg) if per_run_cpu_avg else float("nan"),
        "cpu_max_pct": median(per_run_cpu_max) if per_run_cpu_max else float("nan"),
        "rss_avg_mb":  median(per_run_rss_avg) if per_run_rss_avg else float("nan"),
        "rss_max_mb":  median(per_run_rss_max) if per_run_rss_max else float("nan"),
        "_per_run_latency_medians": per_run_latency_median,  # used for Wilcoxon
        "_per_run_cpu_avg": per_run_cpu_avg,
        "_per_run_rss_avg": per_run_rss_avg,
    }


def holm_bonferroni(pvals):
    """Return list of Holm-Bonferroni adjusted p-values in original order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adjusted = [None] * m
    prev = 0.0
    for rank, i in enumerate(order):
        adj = (m - rank) * pvals[i]
        adj = min(adj, 1.0)
        adj = max(adj, prev)  # monotonicity
        adjusted[i] = adj
        prev = adj
    return adjusted


def pairwise_wilcoxon(results_map):
    """
    Compare RBciAD against OpenViBE and BCI2000 on:
    - per-run latency medians
    - per-run CPU average
    - per-run RSS average
    Using Wilcoxon signed-rank (paired, because same runs / same source).
    """
    if not HAS_SCIPY:
        return []
    rows = []
    raw_pvals = []
    raw_meta = []

    for wf in WORKFLOWS:
        ref = results_map.get(("RBciAD", wf))
        if ref is None:
            continue
        for other in ("OpenViBE", "BCI2000"):
            comp = results_map.get((other, wf))
            if comp is None:
                continue
            for metric, key in [("latency_ms", "_per_run_latency_medians"),
                                ("cpu_avg_pct", "_per_run_cpu_avg"),
                                ("rss_avg_mb",  "_per_run_rss_avg")]:
                a = ref[key]
                b = comp[key]
                n = min(len(a), len(b))
                if n < 3:
                    continue
                a, b = a[:n], b[:n]
                try:
                    stat, p = wilcoxon(a, b, zero_method="wilcox",
                                       alternative="two-sided")
                    raw_pvals.append(float(p))
                    raw_meta.append((wf, other, metric,
                                     median(a), median(b), n, float(stat)))
                except ValueError:
                    continue

    adj = holm_bonferroni(raw_pvals) if raw_pvals else []
    for (wf, other, metric, med_a, med_b, n, stat), p_raw, p_adj in zip(
            raw_meta, raw_pvals, adj):
        rows.append({
            "workflow": wf,
            "comparison": f"RBciAD vs {other}",
            "metric": metric,
            "n_pairs": n,
            "median_RBciAD": f"{med_a:.3f}",
            "median_other": f"{med_b:.3f}",
            "W_stat": f"{stat:.3f}",
            "p_raw": f"{p_raw:.4f}",
            "p_holm": f"{p_adj:.4f}",
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Aggregate cross-platform "
                                                 "benchmark logs.")
    parser.add_argument("--runs-dir", default="runs",
                        help="Root folder containing runs/{platform}/{W*}/")
    parser.add_argument("--out-dir", default="summary",
                        help="Output folder (will be created).")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    results_map = {}
    for plat in PLATFORMS:
        for wf in WORKFLOWS:
            r = aggregate_platform_workflow(args.runs_dir, plat, wf)
            if r is not None:
                results_map[(plat, wf)] = r

    # Write summary CSV
    summary_path = os.path.join(args.out_dir, "cross_platform_summary.csv")
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["platform", "workflow", "n_runs", "n_pulses",
                    "latency_p50_ms", "latency_p95_ms",
                    "cpu_avg_pct", "cpu_max_pct",
                    "rss_avg_mb", "rss_max_mb"])
        for plat in PLATFORMS:
            for wf in WORKFLOWS:
                r = results_map.get((plat, wf))
                if r is None:
                    w.writerow([plat, wf, 0, 0,
                                "NA", "NA", "NA", "NA", "NA", "NA"])
                    continue
                w.writerow([
                    r["platform"], r["workflow"], r["n_runs"], r["n_pulses"],
                    f"{r['latency_p50_ms']:.2f}",
                    f"{r['latency_p95_ms']:.2f}",
                    f"{r['cpu_avg_pct']:.2f}",
                    f"{r['cpu_max_pct']:.2f}",
                    f"{r['rss_avg_mb']:.1f}",
                    f"{r['rss_max_mb']:.1f}",
                ])
    print(f"[aggregate] Wrote {summary_path}")

    # Write pairwise tests
    if HAS_SCIPY:
        tests = pairwise_wilcoxon(results_map)
        tests_path = os.path.join(args.out_dir, "pairwise_tests.csv")
        with open(tests_path, "w", newline="") as f:
            if tests:
                writer = csv.DictWriter(f, fieldnames=tests[0].keys())
                writer.writeheader()
                writer.writerows(tests)
            else:
                f.write("# no tests computed (insufficient data)\n")
        print(f"[aggregate] Wrote {tests_path}")
    else:
        print("[aggregate] scipy not installed -> skipping Wilcoxon tests. "
              "Run: pip install scipy")


if __name__ == "__main__":
    main()
