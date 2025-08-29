# utils/build_tables_standalone.py
# -*- coding: utf-8 -*-
import os, csv, argparse, math, glob
from statistics import median

def _parse_payload(s):
    out = {}
    if not s:
        return out
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
        else:
            k, v = part, ""
        # parse number if possible
        try:
            vlow = v.lower()
            if vlow in ("nan", "+nan", "-nan"):
                out[k] = float("nan")
            elif vlow in ("inf", "+inf"):
                out[k] = float("inf")
            elif vlow in ("-inf",):
                out[k] = float("-inf")
            else:
                if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                    out[k] = int(v)
                else:
                    out[k] = float(v)
        except Exception:
            out[k] = v
    return out

def _safe_median(values):
    vals = [float(x) for x in values if x is not None and not (isinstance(x,float) and math.isnan(x))]
    return median(vals) if vals else None

def _safe_median_pos(values):
    vals = [float(x) for x in values
            if x is not None
            and not (isinstance(x,float) and math.isnan(x))
            and float(x) > 0.0]
    return median(vals) if vals else None

def _p95(values):
    vals = [float(x) for x in values if x is not None and not (isinstance(x,float) and math.isnan(x))]
    if not vals:
        return None
    vals.sort()
    idx = int(round(0.95*(len(vals)-1)))
    return vals[idx]

def process_run(path):
    ts_min = None
    ts_max = None

    frames_rendered = 0
    frames_dropped  = 0
    render_fps      = []   # from RENDER_STATS (>0 only)
    render_drop_pct = []   # from RENDER_STATS (kept when stat looks valid)
    render_thr_sps  = []   # from RENDER_STATS (>0 only)

    cpu_vals = []
    rss_vals = []

    # latency per-frame
    lat_ms_samples = []

    # TTFP
    ts_ttfp_start = None
    ts_first_frame = None
    ttfp_s_direct = None  # from TTFP event

    # filter metrics
    filter_groups = {}      # group -> list(dur_s)
    filter_done_thr = []    # throughput_sps from FILTER_DONE
    n_filter_done = 0
    n_filter_fail = 0
    n_events_total = 0

    # aux counts
    n_param_changes = 0

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            n_events_total += 1
            try:
                ts = int(row[0])
                kind = row[1]
                payload = row[2] if len(row) > 2 else ""
            except Exception:
                continue

            ts_min = ts if ts_min is None else min(ts_min, ts)
            ts_max = ts if ts_max is None else max(ts_max, ts)

            p = _parse_payload(payload)

            # CPU/RSS
            if kind == "CPU_MEM":
                cpu = p.get("cpu")
                rss = p.get("rss_mb")
                if isinstance(cpu, (int,float)):
                    cpu_vals.append(float(cpu))
                if isinstance(rss, (int,float)):
                    rss_vals.append(float(rss))

            # frames + latence par frame
            if kind == "FRAME_RENDERED":
                frames_rendered += 1
                latv = p.get("lat_ms")
                if isinstance(latv, (int,float)):
                    lat_ms_samples.append(float(latv))
            elif kind == "FRAME_DROPPED":
                frames_dropped += 1

            # RENDER_STATS (n'ajouter que des valeurs "utiles")
            if kind == "RENDER_STATS":
                # fps > 0
                fps = p.get("fps")
                if isinstance(fps, (int,float)) and float(fps) > 0.0:
                    render_fps.append(float(fps))

                # throughput: sps/ksps, > 0
                thr = None
                if isinstance(p.get("throughput_sps"), (int,float)):
                    thr = float(p["throughput_sps"])
                elif isinstance(p.get("throughput"), (int,float)):
                    thr = float(p["throughput"])
                elif isinstance(p.get("throughput_ksps"), (int,float)):
                    thr = float(p["throughput_ksps"]) * 1000.0
                if isinstance(thr, (int,float)) and thr is not None and thr > 0.0:
                    render_thr_sps.append(float(thr))

                # dropped_pct : on la garde si au moins un indicateur est valide (>0)
                drop = p.get("dropped_pct", p.get("dropped_frames_pct"))
                if isinstance(drop, (int,float)):
                    if (isinstance(fps, (int,float)) and float(fps) > 0.0) or (isinstance(thr, (int,float)) and thr > 0.0):
                        render_drop_pct.append(float(drop))

            # Autres formes de latence éventuelles
            if kind in ("FRAME_LATENCY","RENDER_LATENCY","RENDER_LATENCY_MS"):
                cand = p.get("latency_ms", p.get("ms", p.get("value")))
                if isinstance(cand, (int,float)):
                    lat_ms_samples.append(float(cand))

            # TTFP markers
            if kind == "START_TTFP":
                if ts_ttfp_start is None:
                    ts_ttfp_start = ts
            if kind == "FIRST_FRAME":
                if ts_first_frame is None:
                    ts_first_frame = ts
            if kind == "TTFP":
                v = p.get("ttfp_s")
                if isinstance(v, (int,float)):
                    ttfp_s_direct = float(v)

            # filters
            if kind == "FILTER_DONE":
                n_filter_done += 1
                g = str(p.get("group", p.get("method", "unknown"))).lower()
                dur = p.get("dur_s")
                if g not in filter_groups:
                    filter_groups[g] = []
                if isinstance(dur, (int,float)):
                    filter_groups[g].append(float(dur))
                thr_f = p.get("throughput_sps")
                if isinstance(thr_f, (int,float)):
                    filter_done_thr.append(float(thr_f))
            elif kind == "FILTER_FAIL":
                n_filter_fail += 1

            if kind == "PARAM_CHANGE":
                n_param_changes += 1

    # runtime
    runtime_s = ((ts_max - ts_min)/1e9) if (ts_min is not None and ts_max is not None and ts_max > ts_min) else None

    # FPS: priorité au comptage strict; sinon médiane des fps>0
    if runtime_s and frames_rendered > 0:
        fps = frames_rendered / runtime_s
    else:
        fps = _safe_median_pos(render_fps)

    # Dropped %: sur les compteurs si possible, sinon médiane des stats
    total_frames = frames_rendered + frames_dropped
    if total_frames > 0:
        dropped_pct = 100.0 * frames_dropped / total_frames
    else:
        dropped_pct = _safe_median(render_drop_pct)

    # Throughput (samples/s): médiane des valeurs >0, sinon FILTER_DONE
    thr_sps = _safe_median_pos(render_thr_sps) or _safe_median(filter_done_thr)

    # TTFP: direct si dispo, sinon delta START->FIRST
    if isinstance(ttfp_s_direct, (int,float)):
        ttfp_s = ttfp_s_direct
    elif ts_ttfp_start is not None and ts_first_frame is not None and ts_first_frame >= ts_ttfp_start:
        ttfp_s = (ts_first_frame - ts_ttfp_start)/1e9
    else:
        ttfp_s = None

    # Latence p50/p95
    lat_p50 = _safe_median(lat_ms_samples)
    lat_p95 = _p95(lat_ms_samples)

    cpu_avg = (sum(cpu_vals)/len(cpu_vals)) if cpu_vals else None
    cpu_max = max(cpu_vals) if cpu_vals else None
    rss_avg = (sum(rss_vals)/len(rss_vals)) if rss_vals else None
    rss_max = max(rss_vals) if rss_vals else None

    return {
        "path": path,
        "runtime_s": runtime_s,
        "cpu_avg": cpu_avg, "cpu_max": cpu_max,
        "rss_avg_mb": rss_avg, "rss_max_mb": rss_max,
        "n_frames": frames_rendered,
        "n_param_changes": n_param_changes,
        "latency_p50_ms": lat_p50,
        "latency_p95_ms": lat_p95,
        "ttfp_s": ttfp_s,
        "n_filter_done": n_filter_done,
        "n_filter_fail": n_filter_fail,
        "n_events_total": n_events_total,
        "fps": fps,
        "throughput_sps": thr_sps,
        "dropped_pct": dropped_pct,
        "filter_groups": filter_groups,
    }

def write_csv(path, rows, header):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(col, "") for col in header])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_dir", help="Dossier contenant les .csv bruts (metrics_logger)")
    ap.add_argument("--outdir", default="out", help="Dossier de sortie")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.runs_dir, "*.csv")))
    if not files:
        print("Aucun fichier dans", args.runs_dir)
        return

    per_run = []
    filter_agg = {}  # group -> list of durations
    filter_done_fail = {}  # group -> {"done": n, "fail": n}

    for fn in files:
        r = process_run(fn)
        per_run.append(r)
        for g, durs in (r.get("filter_groups") or {}).items():
            filter_agg.setdefault(g, []).extend(durs)
            filter_done_fail.setdefault(g, {"done":0,"fail":0})
            filter_done_fail[g]["done"] += len(durs)
        # si vous logguez group dans FILTER_FAIL, vous pouvez l'agréger ici aussi.

    # table1_by_run
    t1_rows = []
    for r in per_run:
        t1_rows.append({
            "path": r["path"],
            "workflow": "W?",  # si vous avez RUN_META.workflow, remplissez-le ici
            "ttfp_s": r["ttfp_s"] if r["ttfp_s"] is not None else "",
            "latency_p50_ms": r["latency_p50_ms"] if r["latency_p50_ms"] is not None else "",
            "latency_p95_ms": r["latency_p95_ms"] if r["latency_p95_ms"] is not None else "",
            "fps": r["fps"] if r["fps"] is not None else "",
            "throughput_sps": r["throughput_sps"] if r["throughput_sps"] is not None else "",
            "dropped_pct": r["dropped_pct"] if r["dropped_pct"] is not None else "",
            "cpu_avg": r["cpu_avg"] if r["cpu_avg"] is not None else "",
            "cpu_max": r["cpu_max"] if r["cpu_max"] is not None else "",
            "rss_avg_mb": r["rss_avg_mb"] if r["rss_avg_mb"] is not None else "",
            "rss_max_mb": r["rss_max_mb"] if r["rss_max_mb"] is not None else "",
            "n_frames": r["n_frames"],
            "n_param_changes": r["n_param_changes"],
        })

    write_csv(
        os.path.join(args.outdir, "table1_by_run.csv"),
        t1_rows,
        ["path","workflow","ttfp_s","latency_p50_ms","latency_p95_ms","fps","throughput_sps","dropped_pct","cpu_avg","cpu_max","rss_avg_mb","rss_max_mb","n_frames","n_param_changes"]
    )

    # table1_summary (médianes sur les runs)
    def _col(col):
        vals=[]
        for r in per_run:
            v = r.get(col)
            if isinstance(v,(int,float)) and not (isinstance(v,float) and math.isnan(v)):
                vals.append(float(v))
        return _safe_median(vals)

    thr_med = _safe_median([r.get("throughput_sps") for r in per_run if r.get("throughput_sps") is not None])

    summary = {
        "workflow": "W?",
        "TTFP (s)": _col("ttfp_s"),
        "Latency P50 (ms)": _col("latency_p50_ms"),
        "Latency P95 (ms)": _col("latency_p95_ms"),
        "FPS": _col("fps"),
        "Throughput (kS/s)": ((thr_med/1000.0) if thr_med is not None else ""),
        "Dropped (%)": _col("dropped_pct"),
        "CPU avg (%)": _col("cpu_avg"),
        "CPU max (%)": _col("cpu_max"),
        "RSS avg (MB)": _col("rss_avg_mb"),
        "RSS max (MB)": _col("rss_max_mb"),
    }
    write_csv(
        os.path.join(args.outdir, "table1_summary.csv"),
        [summary],
        ["workflow","TTFP (s)","Latency P50 (ms)","Latency P95 (ms)","FPS","Throughput (kS/s)","Dropped (%)","CPU avg (%)","CPU max (%)","RSS avg (MB)","RSS max (MB)"]
    )

    # table2_filter_summary
    t2_rows=[]
    for g, durs in filter_agg.items():
        n = len(durs)
        med = _safe_median(durs)
        p95 = _p95(durs)
        done_fail = filter_done_fail.get(g, {"done":0,"fail":0})
        denom = max(1, done_fail["done"] + done_fail["fail"])
        fail_pct = 100.0 * float(done_fail["fail"]) / float(denom)
        t2_rows.append({
            "group": g,
            "n": n,
            "dur_med_s": med if med is not None else "",
            "dur_p95_s": p95 if p95 is not None else "",
            "fail_pct": fail_pct
        })
    t2_rows.sort(key=lambda r: r["group"])
    write_csv(
        os.path.join(args.outdir, "table2_filter_summary.csv"),
        t2_rows,
        ["group","n","dur_med_s","dur_p95_s","fail_pct"]
    )

    print("OK ->", args.outdir)

if __name__ == "__main__":
    main()