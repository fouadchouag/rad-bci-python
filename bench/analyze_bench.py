#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RBciAD — Bench log analyzer
--------------------------------
Entrées : un ou plusieurs fichiers CSV produits par utils.eval_log (ou équivalent)
          avec des lignes du type :
              ts_ns,event,payload
          ex.:
              1712684300123456789,START_TTFP,
              1712684302123123123,RUN,source=emu
              1712684303234567890,SAMPLES_IN,1000
              1712684304456789012,PARAM_CHANGE,win_s=10.0
              1712684305123456789,FRAME,n=1
              1712684306234567000,FIRST_FRAME,frame_id=1
          Le script est volontairement robuste :
              - accepte en-têtes variables : ts_ns|timestamp_ns|time_ns|ts|t
              - si pas d’en-tête, suppose colonnes : ts,event,payload
              - ts en nanosecondes (recommandé) OU secondes (il auto-détecte)
              - payload libre ("k=v" séparés par espaces/virgules) ou juste un nombre

Sorties :
  • Tableau récap par run sur stdout
  • Option --out CSV : exporte les métriques
  • Option --plot : PNG timeline façon Figure 6 (param changes vs frames)

Métriques par run :
  - TTFP (s) = FIRST_FRAME - (dernier START_TTFP précédent)
  - Latency P50 / P95 (ms) = 1er FRAME suivant chaque PARAM_CHANGE
  - FPS = (#FRAME-1) / (t_last_frame - t_first_frame)
  - Throughput (samples/s) = pente SAMPLES_IN vs temps
  - Thru% = 100 * Throughput / SR (passé via --sr)
  - Dropped frames (%) = si événements EXPECTED/RENDERED présents, sinon N/A
"""
from __future__ import annotations

import argparse, csv, math, os, sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Matplotlib n’est importé que si --plot est demandé
_MPL = None

# ----------------------------- parsing -----------------------------

@dataclass
class Event:
    t: float                # timestamp en SECONDES (float)
    kind: str               # "RUN", "START_TTFP", "FRAME", "FIRST_FRAME", "PARAM_CHANGE", "SAMPLES_IN", ...
    payload_raw: str
    payload: Dict[str, str] = field(default_factory=dict)
    file: str = ""
    row_no: int = 0

def _parse_ts(v: str) -> Optional[float]:
    v = (v or "").strip()
    if not v:
        return None
    # numérique ?
    try:
        x = float(v)
        # Heuristique : ns si > ~1e11
        if x > 1e11:
            return x * 1e-9
        # microsecondes rares, mais si >1e6 et <1e11 on assume secondes déjà
        return x
    except Exception:
        pass
    # ISO 8601 (rare) – tolérance minimale
    try:
        from datetime import datetime
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v).timestamp()
    except Exception:
        return None

def _payload_to_dict(s: str) -> Dict[str, str]:
    s = (s or "").strip()
    if not s:
        return {}
    # si juste un nombre -> {"value": <nombre>}
    if s.replace(".", "", 1).isdigit():
        return {"value": s}
    out: Dict[str,str] = {}
    # split par virgule OU espace
    parts = []
    for chunk in s.replace(",", " ").split():
        if chunk:
            parts.append(chunk)
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            # token libre : on les empile sous _t0,_t1 ...
            k = f"_t{len([k for k in out.keys() if k.startswith('_t')])}"
            out[k] = p
    return out

def _read_events_one_file(path: str) -> List[Event]:
    ev: List[Event] = []
    with open(path, "r", newline="") as f:
        # détecte si en-tête
        sample = f.read(4096)
        f.seek(0)
        has_header = any(h in sample.splitlines()[0].lower() for h in ["ts", "time", "event"])
        reader = csv.reader(f)
        if has_header:
            # DictReader avec normalisation des noms de colonnes
            f.seek(0)
            dreader = csv.DictReader(f)
            # retrouver la colonne timestamp
            ts_keys = [k for k in dreader.fieldnames or [] if k and k.lower() in
                       ("ts_ns","timestamp_ns","time_ns","ts","time","t")]
            ts_key = ts_keys[0] if ts_keys else (dreader.fieldnames or [""])[0]
            for i, row in enumerate(dreader, start=2):
                t = _parse_ts(row.get(ts_key, "")) if ts_key in row else None
                kind = (row.get("event") or row.get("kind") or "").strip()
                if not kind and len(row) >= 2:
                    # heuristique: 1ère non-ts = event
                    for k in row:
                        if k != ts_key:
                            kind = (row.get(k) or "").strip()
                            break
                payload = row.get("payload", "")
                # si reste des colonnes non vides, concatène dans payload
                if payload is None:
                    payload = ""
                extras = []
                for k, v in row.items():
                    if k in (ts_key, "event", "kind", "payload"):
                        continue
                    if v and str(v).strip():
                        extras.append(f"{k}={v}")
                if extras:
                    payload = (payload + " " + " ".join(extras)).strip()
                if t is None or not kind:
                    continue
                ev.append(Event(t=t, kind=kind.strip().upper(), payload_raw=payload, payload=_payload_to_dict(payload),
                                file=os.path.basename(path), row_no=i))
        else:
            # pas d’en-tête : ts,event,payload
            for i, row in enumerate(reader, start=1):
                if not row:
                    continue
                if len(row) == 1:
                    # ex: "ts_ns,event,payload" en 1 cellule -> split manuel
                    row = row[0].split(",")
                ts = _parse_ts(row[0]) if len(row) >= 1 else None
                kind = (row[1].strip().upper() if len(row) >= 2 else "")
                payload = row[2] if len(row) >= 3 else ""
                if ts is None or not kind:
                    continue
                ev.append(Event(t=ts, kind=kind, payload_raw=payload, payload=_payload_to_dict(payload),
                                file=os.path.basename(path), row_no=i))
    ev.sort(key=lambda e: e.t)
    return ev

# -------------------------- grouping runs --------------------------

@dataclass
class Run:
    label: str
    events: List[Event]

def split_runs(events: List[Event]) -> List[Run]:
    runs: List[Run] = []
    cur: List[Event] = []
    cur_label = "run0"
    run_idx = 0

    for e in events:
        if e.kind == "RUN":
            # close previous
            if cur:
                runs.append(Run(label=cur_label, events=cur))
            run_idx += 1
            label = e.payload.get("source") or e.payload.get("reset") or f"run{run_idx}"
            cur = [e]
            cur_label = str(label)
        else:
            cur.append(e)
    if cur:
        runs.append(Run(label=cur_label, events=cur))
    # si aucun RUN, on crée un run unique
    if not runs and events:
        runs = [Run(label="run1", events=events)]
    return runs

# --------------------------- computations --------------------------

def _percentile(arr: List[float], p: float) -> Optional[float]:
    if not arr:
        return None
    arr = sorted(arr)
    if len(arr) == 1:
        return arr[0]
    k = (len(arr)-1) * (p/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c: return arr[int(k)]
    return arr[f] + (arr[c]-arr[f]) * (k-f)

def compute_metrics(run: Run, sr_hint: Optional[float]=None) -> Dict[str, Optional[float]]:
    ev = run.events
    t0 = ev[0].t
    # TTFP: dernier START_TTFP -> premier FIRST_FRAME après
    ttfp = None
    t_start = None
    for e in ev:
        if e.kind == "START_TTFP":
            t_start = e.t
        if e.kind == "FIRST_FRAME" and t_start is not None:
            ttfp = e.t - t_start
            break

    # Param-change latencies
    frames_t = [e.t for e in ev if e.kind == "FRAME" or e.kind == "FIRST_FRAME"]
    latencies_ms: List[float] = []
    if frames_t:
        for p in (e for e in ev if e.kind == "PARAM_CHANGE"):
            # 1er frame strictement APRES la modif
            nxt = next((ft for ft in frames_t if ft > p.t), None)
            if nxt is not None:
                latencies_ms.append((nxt - p.t) * 1000.0)

    p50 = _percentile(latencies_ms, 50.0) if latencies_ms else None
    p95 = _percentile(latencies_ms, 95.0) if latencies_ms else None

    # FPS
    fps = None
    if len(frames_t) >= 2:
        fps = (len(frames_t)-1) / (frames_t[-1] - frames_t[0] + 1e-12)
    elif len(frames_t) == 1:
        fps = 0.0

    # Throughput (SAMPLES_IN milestones)
    sp = [(e.t, float(e.payload.get("value", "nan"))) for e in ev if e.kind == "SAMPLES_IN"]
    sp = [(t, v) for (t, v) in sp if math.isfinite(v)]
    sp.sort()
    throughput = None
    if len(sp) >= 2:
        t1, v1 = sp[0]
        t2, v2 = sp[-1]
        dt = (t2 - t1)
        if dt > 0:
            throughput = (v2 - v1) / dt

    # Thru %
    thru_pct = None
    if throughput is not None and sr_hint and sr_hint > 0:
        thru_pct = 100.0 * throughput / float(sr_hint)

    # Dropped frames — on essaie d’inférer si on a EXPECTED/RENDERED
    exp = [(e.t, float(e.payload.get("expected", "nan"))) for e in ev if e.kind == "RENDER_STATS"]
    drp = None
    if exp:
        # dernière ligne
        _, expected = exp[-1]
        rendered = float(next((e.payload.get("rendered") for e in reversed(ev) if e.kind == "RENDER_STATS"), "nan"))
        if expected and math.isfinite(expected) and math.isfinite(rendered) and expected > 0:
            drp = 100.0 * max(0.0, (expected - rendered)) / expected

    return {
        "ttfp_s": ttfp,
        "lat_p50_ms": p50,
        "lat_p95_ms": p95,
        "fps": fps,
        "throughput_sps": throughput,
        "thru_pct": thru_pct,
        "dropped_pct": drp,
        "frames": float(len(frames_t)),
        "param_changes": float(len([e for e in ev if e.kind == "PARAM_CHANGE"])),
        "samples_points": float(len(sp)),
        "t_start": ev[0].t - t0,
        "t_end": ev[-1].t - t0,
    }

# ----------------------------- plotting ----------------------------

def plot_timeline(run: Run, out_png: str):
    global _MPL
    if _MPL is None:
        import matplotlib.pyplot as plt
        _MPL = plt
    plt = _MPL

    t0 = run.events[0].t
    frames = [e for e in run.events if e.kind in ("FRAME","FIRST_FRAME")]
    params = [e for e in run.events if e.kind == "PARAM_CHANGE"]

    plt.figure(figsize=(10, 3.5))
    # frames: points
    if frames:
        x = [e.t - t0 for e in frames]
        y = [0.0 for _ in frames]
        plt.scatter(x, y, s=12, label="FRAME")
    # param changes: traits verticaux
    for p in params:
        tp = p.t - t0
        plt.axvline(tp, linestyle="--", linewidth=1)
    # (optionnel) latences textuelles : uniquement si peu de points
    if frames and params and len(params) <= 12:
        fts = [e.t for e in frames]
        for p in params:
            nxt = next((ft for ft in fts if ft > p.t), None)
            if nxt:
                lat_ms = (nxt - p.t) * 1000.0
                plt.text((p.t - t0), 0.02, f"{lat_ms:.0f} ms", rotation=90, va="bottom", ha="center")
    plt.yticks([], [])
    plt.xlabel("Time (s)")
    plt.title(f"Timeline — {run.label}")
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()

# ------------------------------ main -------------------------------

def main():
    ap = argparse.ArgumentParser(description="RBciAD bench log analyzer")
    ap.add_argument("logs", nargs="+", help="Chemins de log CSV (globs acceptés par le shell)")
    ap.add_argument("--sr", type=float, default=None, help="Sampling rate (Hz) pour Thru% (sinon calculé sans %)")
    ap.add_argument("--out", type=str, default=None, help="Chemin CSV de sortie des métriques")
    ap.add_argument("--plot", action="store_true", help="Génère un PNG timeline pour chaque run")
    ap.add_argument("--plots-dir", type=str, default="bench_plots", help="Dossier des PNG si --plot")
    args = ap.parse_args()

    # agrège tous les événements
    all_events: List[Event] = []
    for p in args.logs:
        if not os.path.exists(p):
            print(f"[warn] fichier introuvable : {p}", file=sys.stderr)
            continue
        ev = _read_events_one_file(p)
        if not ev:
            print(f"[warn] pas d’événements dans : {p}", file=sys.stderr)
            continue
        all_events.extend(ev)

    if not all_events:
        print("Aucun événement trouvé.", file=sys.stderr)
        sys.exit(2)

    all_events.sort(key=lambda e: e.t)
    runs = split_runs(all_events)
    if not runs:
        print("Aucun run détecté (logs sans RUN/événements).", file=sys.stderr)
        sys.exit(3)

    # calcule métriques
    rows_out: List[Tuple[str, Dict[str, Optional[float]]]] = []
    print("Run,label,TTFP(s),Lat P50(ms),Lat P95(ms),FPS,Throughput(samples/s),Thru(%),Dropped(%),Frames,ParamChanges,SamplePts")
    for i, r in enumerate(runs, start=1):
        m = compute_metrics(r, sr_hint=args.sr)
        rows_out.append((r.label, m))
        print("{},{},{},{},{},{},{},{},{},{},{}".format(
            i, r.label,
            f"{m['ttfp_s']:.3f}" if m['ttfp_s'] is not None else "",
            f"{m['lat_p50_ms']:.2f}" if m['lat_p50_ms'] is not None else "",
            f"{m['lat_p95_ms']:.2f}" if m['lat_p95_ms'] is not None else "",
            f"{m['fps']:.3f}" if m['fps'] is not None else "",
            f"{m['throughput_sps']:.2f}" if m['throughput_sps'] is not None else "",
            f"{m['thru_pct']:.2f}" if m['thru_pct'] is not None else "",
            f"{m['dropped_pct']:.2f}" if m['dropped_pct'] is not None else "",
            int(m['frames'] or 0),
            int(m['param_changes'] or 0),
            int(m['samples_points'] or 0),
        ))

    # export CSV si demandé
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["run_idx","label","ttfp_s","lat_p50_ms","lat_p95_ms","fps",
                        "throughput_sps","thru_pct","dropped_pct","frames","param_changes","sample_points"])
            for i, (label, m) in enumerate(rows_out, start=1):
                w.writerow([i,label,
                            m["ttfp_s"] if m["ttfp_s"] is not None else "",
                            m["lat_p50_ms"] if m["lat_p50_ms"] is not None else "",
                            m["lat_p95_ms"] if m["lat_p95_ms"] is not None else "",
                            m["fps"] if m["fps"] is not None else "",
                            m["throughput_sps"] if m["throughput_sps"] is not None else "",
                            m["thru_pct"] if m["thru_pct"] is not None else "",
                            m["dropped_pct"] if m["dropped_pct"] is not None else "",
                            int(m["frames"] or 0),
                            int(m["param_changes"] or 0),
                            int(m["samples_points"] or 0)])

    # timelines (optionnel)
    if args.plot:
        os.makedirs(args.plots_dir, exist_ok=True)
        for i, r in enumerate(runs, start=1):
            out_png = os.path.join(args.plots_dir, f"timeline_run_{i:02d}_{r.label}.png")
            try:
                plot_timeline(r, out_png)
                print(f"[plot] {out_png}")
            except Exception as e:
                print(f"[plot] échec pour {r.label}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
