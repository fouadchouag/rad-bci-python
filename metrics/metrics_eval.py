
# utils/metrics\_eval.py (final)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyse de logs CSV (RUN_META, CPU_MEM, PARAM_CHANGE, FRAME_RENDERED,
FILTER_START/DONE/FAIL, FIRST_FRAME, ...)

Usage:
  python utils/metrics_eval.py runs --outdir metrics_results
  python utils/metrics_eval.py runs/*.csv other_dir --outdir out
"""
import argparse, csv, os, sys, glob
from collections import defaultdict, deque

# ---------------- utils ----------------
def _ns_to_s(ns):
    try:
        return float(ns) / 1e9
    except Exception:
        return float('nan')

def _parse_payload(s):
    # "k=v,k2=v2" -> dict ; tolère espaces ; préserve messages libres sous la clé 'msg'
    out = {}
    if not s:
        return out
    txt = s.strip().strip('"')
    parts, buf, depth = [], [], 0
    for ch in txt:
        if ch in '([{': depth += 1
        elif ch in ')]}': depth = max(0, depth-1)
        if ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf: parts.append(''.join(buf))
    for p in parts:
        if not p.strip():
            continue
        if '=' in p:
            k, v = p.split('=', 1)
            out[k.strip()] = v.strip()
        else:
            out.setdefault('msg', p.strip())
    return out

# ---------------- discovery ----------------
def _find_logs_from_paths(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, '**', '*.csv'), recursive=True)
        elif os.path.isfile(p):
            files.append(p)
        else:
            files += glob.glob(p, recursive=True)
    files = [f for f in files if os.path.isfile(f)]
    files_sorted = sorted(files, key=lambda x: (os.path.basename(x) != 'run.csv', x))
    return files_sorted

# ---------------- analysis ----------------
def _percentile(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    if len(xs) == 1:
        return float(xs[0])
    q = max(0.0, min(100.0, float(q)))
    k = (len(xs) - 1) * (q/100.0)
    f = int(k)
    c = min(f+1, len(xs)-1)
    if f == c:
        return float(xs[int(k)])
    d0 = xs[f] * (c - k)
    d1 = xs[c] * (k - f)
    return float(d0 + d1)

def analyze_file(path):
    cpu_vals, rss_vals = [], []
    fps_vals, drop_vals, thr_vals = [], [], []

    first_ts = None
    last_ts  = None

    # events
    events_count = defaultdict(int)

    # param -> next frame latency (ms)
    param_times = []   # (ts_ns, name, old, new)
    frame_times = []   # ts_ns

    # TTFP
    start_ts = None    # RUN_META or START_TTFP
    first_frame_ts = None

    # Filter pairing
    open_filter_start = None
    filter_items = []  # dicts

    with open(path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row: continue
            try:
                ts = int(row[0]); ev = row[1].strip(); payload_raw = row[2] if len(row) > 2 else ''
            except Exception:
                continue

            if first_ts is None:
                first_ts = ts
            last_ts = ts
            events_count[ev] += 1

            payload = _parse_payload(payload_raw)

            if ev == 'CPU_MEM':
                try:
                    if 'cpu' in payload: cpu_vals.append(float(payload['cpu']))
                    if 'rss_mb' in payload: rss_vals.append(float(payload['rss_mb']))
                except Exception: pass

            elif ev == 'RUN_META' and start_ts is None:
                start_ts = ts
            elif ev == 'START_TTFP' and start_ts is None:
                start_ts = ts

            elif ev == 'FIRST_FRAME':
                if first_frame_ts is None:
                    first_frame_ts = ts
            elif ev == 'FRAME_RENDERED':
                frame_times.append(ts)

            elif ev == 'RENDER_STATS':
                try:
                    if 'fps' in payload:
                        fps_vals.append(float(payload['fps']))
                    if 'dropped_frames_pct' in payload:
                        drop_vals.append(float(payload['dropped_frames_pct']))
                    # throughput: on accepte 'throughput_sps' ou 'throughput_kSps'
                    if 'throughput_sps' in payload:
                        thr_vals.append(float(payload['throughput_sps']))
                    elif 'throughput_kSps' in payload:
                        thr_vals.append(1000.0 * float(payload['throughput_kSps']))
                except Exception:
                    pass

            elif ev == 'PARAM_CHANGE':
                param_times.append((ts, payload.get('name', ''), payload.get('old', ''), payload.get('new', '')))

            elif ev == 'FILTER_START':
                open_filter_start = ts
                filter_items.append({
                    'start': _ns_to_s(ts), 'end': None, 'duration_s': None,
                    'status': 'RUNNING', 'payload_start': payload, 'payload_end_or_err': {}
                })

            elif ev == 'FILTER_DONE':
                # close last running
                for it in reversed(filter_items):
                    if it['status'] == 'RUNNING':
                        it['end'] = _ns_to_s(ts)
                        try:
                            it['duration_s'] = _ns_to_s(int(ts) - int(float(it['start'])*1e9))
                        except Exception:
                            it['duration_s'] = None
                        it['status'] = 'DONE'
                        break
                open_filter_start = None

            elif ev == 'FILTER_FAIL':
                for it in reversed(filter_items):
                    if it['status'] == 'RUNNING':
                        it['end'] = _ns_to_s(ts)
                        try:
                            it['duration_s'] = _ns_to_s(int(ts) - int(float(it['start'])*1e9))
                        except Exception:
                            it['duration_s'] = None
                        it['status'] = 'FAIL'
                        it['payload_end_or_err'] = payload
                        break
                open_filter_start = None

    runtime_s = _ns_to_s(last_ts - first_ts) if (first_ts is not None and last_ts is not None) else float('nan')

    # TTFP
    ttfp_s = None
    if start_ts is not None and first_frame_ts is not None and first_frame_ts >= start_ts:
        ttfp_s = _ns_to_s(first_frame_ts - start_ts)

    # latencies PARAM_CHANGE -> next FRAME_RENDERED (ms)
    lat_ms = []
    if frame_times:
        j = 0
        nF = len(frame_times)
        for (t, _name, _old, _new) in param_times:
            while j < nF and frame_times[j] < t:
                j += 1
            if j < nF:
                lat_ms.append((frame_times[j] - t) / 1e6)
    lat_p50 = _percentile(lat_ms, 50.0) if lat_ms else float('nan')
    lat_p95 = _percentile(lat_ms, 95.0) if lat_ms else float('nan')

    res_summary = {
        'path': path,
        'runtime_s': runtime_s,
        'cpu_avg': (sum(cpu_vals)/len(cpu_vals)) if cpu_vals else float('nan'),
        'cpu_max': max(cpu_vals) if cpu_vals else float('nan'),
        'rss_avg_mb': (sum(rss_vals)/len(rss_vals)) if rss_vals else float('nan'),
        'rss_max_mb': max(rss_vals) if rss_vals else float('nan'),
        'n_param_changes': len(param_times),
        'n_frames': len(frame_times),
        'latency_p50_ms': lat_p50,
        'latency_p95_ms': lat_p95,
        'ttfp_s': ttfp_s if ttfp_s is not None else '',
        'n_events_total': sum(events_count.values()),
        'n_filter_done': sum(1 for it in filter_items if it.get('status') == 'DONE'),
        'n_filter_fail': sum(1 for it in filter_items if it.get('status') == 'FAIL'),
        'fps_avg': (sum(fps_vals)/len(fps_vals)) if fps_vals else float('nan'),
        'dropped_pct_avg': (sum(drop_vals)/len(drop_vals)) if drop_vals else float('nan'),
        'throughput_kSps_avg': (sum(thr_vals)/len(thr_vals)) if thr_vals else float('nan'),
        'fps': (sum(fps_vals)/len(fps_vals)) if fps_vals else float('nan'),
        'throughput_sps': (sum(thr_vals)/len(thr_vals)) if thr_vals else float('nan'),
        'dropped_pct': (sum(drop_vals)/len(drop_vals)) if drop_vals else float('nan')

    }

    # build per-filter CSV rows
    filter_rows = []
    for it in filter_items:
        row = {
            'log': path,
            'start_s': it.get('start'),
            'end_s': it.get('end'),
            'duration_s': it.get('duration_s'),
            'status': it.get('status'),
        }
        params = it.get('payload_start') or {}
        row['hp'] = params.get('hp')
        row['lp'] = params.get('lp')
        row['enable_hp'] = params.get('enable_hp')
        row['enable_lp'] = params.get('enable_lp')
        row['enable_notch'] = params.get('enable_notch')
        row['method'] = params.get('method')
        row['phase'] = params.get('phase')
        row['picks'] = params.get('picks')
        row['in_place'] = params.get('in_place')
        end_info = it.get('payload_end_or_err') or {}
        row['error'] = end_info.get('error') or end_info.get('msg') or ''
        filter_rows.append(row)

    # build per-param latency CSV rows
    lat_rows = []
    for idx, (t, name, old, new) in enumerate(param_times, 1):
        # find next frame
        next_frame = next((ft for ft in frame_times if ft >= t), None)
        latency_ms = ((next_frame - t)/1e6) if next_frame is not None else ''
        lat_rows.append({
            'log': path,
            'i': idx,
            'ts_s': _ns_to_s(t),
            'name': name,
            'old': old,
            'new': new,
            'latency_ms': latency_ms,
        })

    return res_summary, filter_rows, lat_rows

# ---------------- writing helpers ----------------
def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fieldnames})

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description='Évalue des logs de métriques (CSV).')
    ap.add_argument('paths', nargs='+', help='Fichiers ou dossiers (ex: runs).')
    ap.add_argument('--outdir', default='metrics_results', help='Dossier de sortie (CSV).')
    args = ap.parse_args()

    files = _find_logs_from_paths(args.paths)
    if not files:
        print('Aucun fichier trouvé.')
        sys.exit(1)

    all_summary = []
    all_filters = []
    all_lat = []

    for f in files:
        try:
            summary, filters, lat = analyze_file(f)
            all_summary.append(summary)
            all_filters.extend(filters)
            all_lat.extend(lat)
            rt = summary['runtime_s']
            p50 = summary['latency_p50_ms']; p95 = summary['latency_p95_ms']
            print(f"[OK] {f} | runtime={rt:.2f}s  CPU(avg/max)={summary['cpu_avg']:.1f}/{summary['cpu_max']:.1f}%  "
                  f"RSS(avg/max)={summary['rss_avg_mb']:.0f}/{summary['rss_max_mb']:.0f} MB  "
                  f"frames={summary['n_frames']}  params={summary['n_param_changes']}  "
                  f"P50={p50:.1f}ms  P95={p95:.1f}ms")
        except Exception as e:
            print(f"[WARN] {f}: {e}")

    out_summary = os.path.join(args.outdir, 'summary.csv')
    out_filters = os.path.join(args.outdir, 'filters.csv')
    out_lat = os.path.join(args.outdir, 'latencies.csv')

    write_csv(out_summary, all_summary, fieldnames=[
        'path','runtime_s','cpu_avg','cpu_max','rss_avg_mb','rss_max_mb',
        'n_frames','n_param_changes','latency_p50_ms','latency_p95_ms','ttfp_s',
        'n_filter_done','n_filter_fail','n_events_total','fps','throughput_sps','dropped_pct'

    ])
    write_csv(out_filters, all_filters, fieldnames=[
        'log','start_s','end_s','duration_s','status',
        'hp','lp','enable_hp','enable_lp','enable_notch','method','phase','picks','in_place','error'
    ])
    write_csv(out_lat, all_lat, fieldnames=['log','i','ts_s','name','old','new','latency_ms'])

    print(f"\nRésumé écrit dans:\n  - {out_summary}\n  - {out_filters}\n  - {out_lat}")

if __name__ == '__main__':
    main()