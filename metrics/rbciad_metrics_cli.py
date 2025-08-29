
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RBciAD Metrics CLI — v2
- --metrics: aggregated CSV -> augmented table + charts
- --events:  event logs -> latency stats (+ histogram)
- --multipanel: stitch key charts into a single figure
- --timeline: draw a PARAM_CHANGE→FRAME timeline figure from events

Example:
  python rbciad_metrics_cli.py --metrics metrics.csv --outdir out --multipanel
  python rbciad_metrics_cli.py --events run1.csv run2.csv --outdir out_evt --timeline
"""
import os, sys, math
from pathlib import Path
from typing import List, Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

try:
    from PIL import Image, ImageOps
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

FRAME_EVENTS = {"FIRST_FRAME", "FRAME", "RENDER_FRAME"}
PARAM_EVENT = "PARAM_CHANGE"
TTFP_START = "START_TTFP"

def _ensure_outdir(outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)

def _save_bar(series, title, ylabel, outpath, thresholds=None):
    plt.figure()
    series.plot(kind='bar')
    plt.title(title)
    plt.ylabel(ylabel)
    if thresholds:
        for y, style in thresholds:
            plt.axhline(y, linestyle=style)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200, bbox_inches='tight')
    plt.close()

def _save_grouped_bar(df_sub, title, ylabel, outpath, thresholds=None):
    plt.figure()
    df_sub.plot(kind='bar')
    plt.title(title)
    plt.ylabel(ylabel)
    if thresholds:
        for y, style in thresholds:
            plt.axhline(y, linestyle=style)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200, bbox_inches='tight')
    plt.close()

def _stitch_multipanel(outdir: Path, target_name="RBciAD_Figure_Multipanel.png"):
    if not HAVE_PIL:
        print("[WARN] PIL not available; skipping multipanel stitch.")
        return None
    # Expected charts (if missing, they are skipped/blank)
    candidates = [
        "chart_latency_with_thresholds.png",
        "chart_ttfp_with_thresholds.png",
        "chart_fps_with_thresholds.png",
        "chart_throughput.png",
        "chart_cpu.png",
        "chart_memory.png",
    ]
    imgs = []
    for name in candidates:
        p = outdir / name
        if p.exists():
            imgs.append(Image.open(p))
        else:
            imgs.append(Image.new("RGB", (800, 600), "white"))
    max_w = max(im.width for im in imgs)
    max_h = max(im.height for im in imgs)
    norm = [ImageOps.contain(im, (max_w, max_h)) for im in imgs]
    cols, rows = 3, 2
    canvas = Image.new("RGB", (cols*max_w, rows*max_h), "white")
    for i, im in enumerate(norm):
        r, c = divmod(i, cols)
        canvas.paste(im, (c*max_w, r*max_h))
    outpath = outdir / target_name
    canvas.save(outpath, format="PNG")
    print(f"[OK] Multipanel written -> {outpath}")
    return outpath

def process_metrics_csv(metrics_csv: Path, outdir: Path, multipanel: bool=False):
    _ensure_outdir(outdir)
    df = pd.read_csv(metrics_csv)
    if 'workflow' not in df.columns:
        raise ValueError("Expected a 'workflow' column in metrics CSV.")
    idxed = df.set_index('workflow')
    # Δ% vs W1
    if 'W1' in idxed.index:
        baseline = idxed.loc['W1']
        cols = [c for c in df.columns if c != 'workflow']
        delta = idxed[cols].apply(lambda col: (col - baseline[col.name]) / baseline[col.name] * 100.0, axis=0)
        delta = delta.add_suffix(" Δ% vs W1")
        df_out = idxed.join(delta).reset_index()
    else:
        df_out = df.copy()

    out_csv = outdir / "RBciAD_metrics_augmented.csv"
    df_out.to_csv(out_csv, index=False)

    # Charts
    lat_cols = [c for c in df.columns if c.lower().startswith('latency ')]
    if lat_cols:
        _save_grouped_bar(
            idxed[lat_cols],
            "Latency by Workflow with UX Thresholds",
            "Milliseconds",
            outdir / "chart_latency_with_thresholds.png",
            thresholds=[(100,'--'),(200,':'),(500,'-.'),(1000,'--')]
        )
    if 'TTFP (s)' in idxed.columns:
        _save_bar(
            idxed['TTFP (s)'],
            "TTFP by Workflow with Classic HCI Landmarks",
            "Seconds",
            outdir / "chart_ttfp_with_thresholds.png",
            thresholds=[(0.1,'--'),(1.0,':'),(10.0,'-.')]
        )
    if 'FPS' in idxed.columns:
        _save_bar(
            idxed['FPS'],
            "Display FPS by Workflow with 60/30 FPS Markers",
            "Frames per second",
            outdir / "chart_fps_with_thresholds.png",
            thresholds=[(60,'--'),(30,':')]
        )
    if 'Throughput (kS/s)' in idxed.columns:
        _save_bar(
            idxed['Throughput (kS/s)'],
            "Throughput by Workflow",
            "kSamples/s (across channels)",
            outdir / "chart_throughput.png",
            thresholds=None
        )
    if 'Dropped (%)' in idxed.columns:
        _save_bar(
            idxed['Dropped (%)'],
            "Dropped Frames by Workflow (5% Acceptance Target)",
            "Percent",
            outdir / "chart_dropped_with_target.png",
            thresholds=[(5.0,'--')]
        )
    cpu_cols = [c for c in ['CPU avg (%)','CPU max (%)'] if c in idxed.columns]
    if cpu_cols:
        _save_grouped_bar(
            idxed[cpu_cols],
            "CPU Utilization by Workflow",
            "Percent",
            outdir / "chart_cpu.png",
            thresholds=None
        )
    mem_cols = [c for c in ['RSS avg (MB)','RSS max (MB)'] if c in idxed.columns]
    if mem_cols:
        _save_grouped_bar(
            idxed[mem_cols],
            "Memory (RSS) by Workflow",
            "MB",
            outdir / "chart_memory.png",
            thresholds=None
        )

    print(f"[OK] Metrics processed -> {out_csv} and charts in {outdir}")
    if multipanel:
        _stitch_multipanel(outdir)

def _parse_events_csv(path: Path):
    df = pd.read_csv(path)
    # Normalize columns
    if 'ts_us' in df.columns and 'ev' in df.columns:
        ts = df['ts_us'].astype(float).values
        ev = df['ev'].astype(str).values
    elif 'timestamp' in df.columns and 'event' in df.columns:
        ts = df['timestamp'].astype(float).values
        ev = df['event'].astype(str).values
        if np.nanmax(ts) < 1e6:  # seconds -> microseconds
            ts = ts * 1e6
    else:
        raise ValueError(f"Unrecognized format in {path.name}. Expected (ts_us,ev) or (timestamp,event).")
    order = np.argsort(ts)
    return ts[order], ev[order]

def compute_latency_from_events(paths: List[Path], outdir: Path, make_timeline: bool=False, prefix="events"):
    _ensure_outdir(outdir)
    all_lat_ms = []
    pairs: List[Tuple[float,float,float]] = []  # (t_change_sec, t_frame_sec, latency_ms) for timeline
    ttfp_s = None

    # Merge all files
    merged_ts = []
    merged_ev = []
    for p in paths:
        ts, ev = _parse_events_csv(p)
        merged_ts.extend(ts.tolist())
        merged_ev.extend(ev.tolist())

    # Sort merged
    order = np.argsort(merged_ts)
    ts = np.array(merged_ts, dtype=float)[order]
    ev = np.array(merged_ev, dtype=str)[order]

    # TTFP: last START_TTFP -> first frame after
    start_ts = None
    for t, e in zip(ts, ev):
        if e == TTFP_START:
            start_ts = t
    if start_ts is not None:
        frame_ts = None
        for t, e in zip(ts, ev):
            if t > start_ts and e in FRAME_EVENTS:
                frame_ts = t
                break
        if frame_ts is not None:
            ttfp_s = (frame_ts - start_ts) / 1e6

    # Latencies: each PARAM_CHANGE -> next frame
    change_times = [t for t, e in zip(ts, ev) if e == PARAM_EVENT]
    frame_times  = [t for t, e in zip(ts, ev) if e in FRAME_EVENTS]
    for ct in change_times:
        nf = [ft for ft in frame_times if ft > ct]
        if nf:
            lat_ms = (nf[0] - ct) / 1000.0
            all_lat_ms.append(lat_ms)
            pairs.append((ct/1e6, nf[0]/1e6, lat_ms))

    # Stats
    res = {}
    if all_lat_ms:
        arr = np.array(all_lat_ms, dtype=float)
        res['count'] = int(arr.size)
        res['latency_p50_ms'] = float(np.percentile(arr, 50))
        res['latency_p95_ms'] = float(np.percentile(arr, 95))
    else:
        res['count'] = 0
        res['latency_p50_ms'] = None
        res['latency_p95_ms'] = None
    res['ttfp_s'] = ttfp_s

    # Save summary
    out_csv = outdir / f"{prefix}_latency_from_events_summary.csv"
    pd.DataFrame([res]).to_csv(out_csv, index=False)

    # Save per-change latencies
    lat_rows = [{'t_change_s': a, 't_frame_s': b, 'latency_ms': c} for (a,b,c) in pairs]
    out_lat_csv = outdir / f"{prefix}_latency_pairs.csv"
    pd.DataFrame(lat_rows).to_csv(out_lat_csv, index=False)

    # Histogram
    out_hist = None
    if all_lat_ms:
        plt.figure()
        plt.hist(all_lat_ms, bins=30)
        plt.title("PARAM_CHANGE → first FRAME latency (ms)")
        plt.xlabel("Latency (ms)")
        plt.ylabel("Count")
        for y in [100, 200, 500, 1000]:
            plt.axvline(y, linestyle='--')
        plt.tight_layout()
        out_hist = outdir / f"{prefix}_latency_hist.png"
        plt.savefig(out_hist, dpi=200, bbox_inches='tight')
        plt.close()

    # Timeline
    out_timeline = None
    if make_timeline and pairs:
        # Single-plot timeline: changes at y=0 (^), frames at y=1 (.), lines connecting pairs
        plt.figure()
        t0 = min([a for (a,_,_) in pairs] + [b for (_,b,_) in pairs])
        # Draw markers
        ch_times = [a - t0 for (a,_,_) in pairs]
        fr_times = [b - t0 for (_,b,_) in pairs]
        plt.plot(ch_times, [0]*len(ch_times), marker='^', linestyle='None', label='PARAM_CHANGE')
        plt.plot(fr_times, [1]*len(fr_times), marker='.', linestyle='None', label='FRAME')
        # Connections + labels
        for (a,b,lat) in pairs:
            xa, xb = a - t0, b - t0
            plt.plot([xa, xb],[0,1])
            # light annotation (avoid heavy clutter for large N)
            midx = (xa+xb)/2.0
            midy = 0.5
            plt.text(midx, midy, f"{lat:.0f} ms", ha='center', va='center')
        plt.yticks([0,1], ["change","frame"])
        plt.xlabel("Time (s) since first event")
        plt.title("Timeline: PARAM_CHANGE → first FRAME")
        plt.legend()
        plt.tight_layout()
        out_timeline = outdir / f"{prefix}_timeline.png"
        plt.savefig(out_timeline, dpi=200, bbox_inches='tight')
        plt.close()

    print(f"[OK] Events parsed -> {out_csv} ; histogram: {out_hist} ; timeline: {out_timeline}")
    return out_csv, out_lat_csv, out_hist, out_timeline

def main():
    import argparse
    ap = argparse.ArgumentParser(description="RBciAD Metrics CLI")
    ap.add_argument("--metrics", type=str, help="Aggregated metrics CSV path")
    ap.add_argument("--events", nargs='*', help="Event log CSV paths (PARAM_CHANGE/FRAME)")
    ap.add_argument("--outdir", type=str, required=True, help="Output directory")
    ap.add_argument("--multipanel", action="store_true", help="Stitch key charts into a single figure")
    ap.add_argument("--timeline", action="store_true", help="Draw a timeline figure from events")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    ran = False
    if args.metrics:
        process_metrics_csv(Path(args.metrics), outdir, multipanel=args.multipanel); ran = True
    if args.events:
        paths = [Path(p) for p in args.events]
        compute_latency_from_events(paths, outdir, make_timeline=args.timeline); ran = True
    if not ran:
        ap.error("Please provide --metrics and/or --events")

if __name__ == "__main__":
    main()
