# scripts/analyse_throughput.py
import argparse, csv, json, os

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

def window(events, t0=None, t1=None):
    if t0 is None and t1 is None:
        return events
    sel = []
    for t,n,m in events:
        if (t0 is None or t >= t0) and (t1 is None or t <= t1):
            sel.append((t,n,m))
    return sel

def parse_int(s, default=0):
    try: return int(s)
    except: return default

def compute_throughput(evts):
    # SAMPLES_IN: meta = cumul samples_in
    s_ev = [(t, parse_int(m)) for t,n,m in evts if n == "SAMPLES_IN"]
    if len(s_ev) >= 2:
        t0, s0 = s_ev[0]
        t1, s1 = s_ev[-1]
        dur_s = (t1 - t0) / 1e9
        thr = (s1 - s0) / dur_s if dur_s > 0 else None
    else:
        thr, dur_s = None, None

    # FRAMES_STAT: meta = "drawn,attempted" cumulés
    f_ev = []
    for t,n,m in evts:
        if n == "FRAMES_STAT" and "," in m:
            a,b = m.split(",",1)
            drawn = parse_int(a)
            attempted = parse_int(b)
            f_ev.append((t, drawn, attempted))

    dropped_pct = None
    fps = None
    if len(f_ev) >= 2:
        t0, d0, a0 = f_ev[0]
        t1, d1, a1 = f_ev[-1]
        drawn = max(0, d1 - d0)
        attempted = max(1, a1 - a0)
        dropped_pct = 100.0 * (1.0 - (drawn / attempted))
        dur_s_f = (t1 - t0) / 1e9
        fps = drawn / dur_s_f if dur_s_f > 0 else None

    return {
        "throughput_samples_per_s": thr,
        "duration_samples_window_s": dur_s,
        "frames_per_s": fps,
        "dropped_frames_percent": dropped_pct,
    }

def main():
    ap = argparse.ArgumentParser(description="Analyse throughput & dropped frames")
    ap.add_argument("csv_path", help="Path to eval_log.csv")
    ap.add_argument("--from_ns", type=int, default=None, help="Start time (ns) to bound analysis")
    ap.add_argument("--to_ns", type=int, default=None, help="End time (ns) to bound analysis")
    ap.add_argument("--out", default=None, help="Write JSON to this file")
    args = ap.parse_args()

    evts = read_events(args.csv_path)
    evts_w = window(evts, args.from_ns, args.to_ns)
    res = compute_throughput(evts_w)
    print(json.dumps(res, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
