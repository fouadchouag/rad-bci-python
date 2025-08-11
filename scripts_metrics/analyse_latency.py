# scripts/analyse_latency.py
import argparse, csv, json, os
from statistics import median
import numpy as np

def read_events(path):
    evts = []
    with open(path, newline="") as f:
        r = csv.reader(f)
        for row in r:
            if not row: continue
            try:
                t_ns = int(row[0].strip())
                name = row[1].strip()
                meta = row[2].strip() if len(row) > 2 else ""
                evts.append((t_ns, name, meta))
            except Exception:
                pass
    evts.sort(key=lambda x: x[0])
    return evts

def compute_ttfp(evts):
    # paires (START_TTFP -> FIRST_FRAME après)
    starts = [t for t,n,_ in evts if n == "START_TTFP"]
    frames = [t for t,n,_ in evts if n == "FIRST_FRAME"]
    ttfp_ms = []
    for s in starts:
        nf = next((tf for tf in frames if tf > s), None)
        if nf: ttfp_ms.append((nf - s) / 1e6)
    return {
        "count": len(ttfp_ms),
        "p50_ms": float(np.percentile(ttfp_ms, 50)) if ttfp_ms else None,
        "p95_ms": float(np.percentile(ttfp_ms, 95)) if ttfp_ms else None,
        "all_ms": ttfp_ms,
    }

def compute_latency(evts):
    params = [t for t,n,_ in evts if n == "PARAM_CHANGE"]
    frames = [t for t,n,_ in evts if n == "FRAME"]
    dts = []
    i = 0
    for t0 in params:
        # avance l'index frames pour garder la recherche amortie O(1)
        while i < len(frames) and frames[i] <= t0:
            i += 1
        if i < len(frames):
            dts.append((frames[i] - t0) / 1e6)  # ms
    return {
        "count_pairs": len(dts),
        "p50_ms": float(np.percentile(dts, 50)) if dts else None,
        "p95_ms": float(np.percentile(dts, 95)) if dts else None,
        "median_ms": float(median(dts)) if dts else None,
    }

def main():
    ap = argparse.ArgumentParser(description="Analyse TTFP & UI latency from eval_log.csv")
    ap.add_argument("csv_path", help="Path to eval_log.csv")
    ap.add_argument("--out", default=None, help="Write JSON results to this file")
    args = ap.parse_args()

    evts = read_events(args.csv_path)
    ttfp = compute_ttfp(evts)
    lat = compute_latency(evts)

    res = {"ttfp": ttfp, "latency": lat}
    print(json.dumps(res, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
