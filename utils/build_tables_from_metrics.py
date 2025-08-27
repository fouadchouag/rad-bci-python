#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, csv, argparse
import pandas as pd
import numpy as np

# -------------- helpers --------------
def _parse_kv_payload(txt: str):
    """Parse 'k=v,k2=v2' tolérant les espaces; retourne dict."""
    out = {}
    if not txt: return out
    s = txt.strip().strip('"')
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch in '([{': depth += 1
        elif ch in ')]}': depth = max(0, depth-1)
        if ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf=[]
        else:
            buf.append(ch)
    if buf: parts.append(''.join(buf))
    for p in parts:
        p = p.strip()
        if not p: continue
        if '=' in p:
            k,v = p.split('=',1)
            out[k.strip()] = v.strip()
    return out

def _infer_workflow_from_name(path):
    m = re.search(r'(W[123])', os.path.basename(path), flags=re.IGNORECASE)
    return m.group(1).upper() if m else 'W?'

def _to_float(x):
    """Conversion souple vers float (coerce string/None)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().lower().replace(',', '.')
    m = re.search(r'-?\d+(\.\d+)?', s)
    if not m:
        return np.nan
    return float(m.group(0))

def _scan_stats_from_raw(raw_path):
    """
    Récupère throughput (samples/s) depuis READER_STATS
    et dropped frames (%) depuis RENDER_STATS, si disponibles.
    """
    thr = np.nan
    dropped_pct = np.nan
    if not os.path.isfile(raw_path):
        return thr, dropped_pct
    try:
        with open(raw_path, 'r', encoding='utf-8') as f:
            r = csv.reader(f)
            for row in r:
                if not row: continue
                ev = row[1].strip() if len(row)>1 else ''
                payload = row[2] if len(row)>2 else ''
                if ev == 'READER_STATS':
                    d = _parse_kv_payload(payload)
                    for k in ('throughput','samples_per_s','sps','rate_sps'):
                        if k in d:
                            thr = _to_float(d[k]); break
                elif ev == 'RENDER_STATS':
                    try:
                        if 'fps' in payload: fps_vals.append(float(payload['fps']))
                        if 'dropped_frames_pct' in payload: drop_vals.append(float(payload['dropped_frames_pct']))
                        # supporte anciens/ nouveaux noms : throughput_kSps ou throughput_sps
                        val = payload.get('throughput_kSps') or payload.get('throughput_sps')
                        if val is not None: thr_vals.append(float(val))
                    except Exception:
                        pass
    except Exception:
        pass
    return thr, dropped_pct

def p95_series(x):
    x = pd.to_numeric(x, errors='coerce').dropna().to_numpy()
    return float(np.percentile(x, 95)) if x.size else np.nan

# -------------- table 1 --------------
def build_table1(metrics_dir, out_dir, rescan_raw=True):
    os.makedirs(out_dir, exist_ok=True)
    summ_path = os.path.join(metrics_dir, 'summary.csv')
    if not os.path.isfile(summ_path):
        raise FileNotFoundError(f"summary.csv introuvable dans {metrics_dir}")

    df = pd.read_csv(summ_path)

    # FPS par run (approx): n_frames / runtime_s
    df['fps'] = df.apply(lambda r: (r['n_frames']/r['runtime_s']) if (r.get('runtime_s',0)>0) else np.nan, axis=1)

    # Optionnel: rescanner chaque log brut pour throughput et dropped
    thr_list, drop_list, wf_list = [], [], []
    for _, r in df.iterrows():
        raw = r['path']
        wf  = _infer_workflow_from_name(raw)
        wf_list.append(wf)
        if rescan_raw:
            thr, dr = _scan_stats_from_raw(raw)
        else:
            thr, dr = (np.nan, np.nan)
        thr_list.append(thr)
        drop_list.append(dr)
    df['workflow'] = wf_list
    df['throughput_sps'] = thr_list
    df['dropped_pct'] = drop_list

    # Conversion NUMÉRIQUE robuste pour toutes les colonnes utilisées
    num_cols = [
        'ttfp_s','latency_p50_ms','latency_p95_ms','fps',
        'throughput_sps','dropped_pct','cpu_avg','cpu_max',
        'rss_avg_mb','rss_max_mb','n_frames','n_param_changes','runtime_s'
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    # Export par run
    cols = [
        'path','workflow','ttfp_s','latency_p50_ms','latency_p95_ms',
        'fps','throughput_sps','dropped_pct','cpu_avg','cpu_max','rss_avg_mb','rss_max_mb','n_frames','n_param_changes'
    ]
    by_run = df[cols].sort_values(['workflow','path'])
    by_run.to_csv(os.path.join(out_dir, 'table1_by_run.csv'), index=False)

    # Agrégat par workflow (médianes robustes)
    g = by_run.groupby('workflow', dropna=False)

    med_ttfp   = g['ttfp_s'].median()
    med_p50    = g['latency_p50_ms'].median()
    med_p95    = g['latency_p95_ms'].median()
    med_fps    = g['fps'].median()
    med_thr    = g['throughput_sps'].median()
    med_drop   = g['dropped_pct'].median()
    med_cpu_a  = g['cpu_avg'].median()
    med_cpu_m  = g['cpu_max'].median()
    med_rss_a  = g['rss_avg_mb'].median()
    med_rss_m  = g['rss_max_mb'].median()

    summary = pd.DataFrame({
        'workflow': med_ttfp.index,
        'TTFP (s)': med_ttfp.values.round(2),
        'Latency P50 (ms)': med_p50.values.round(1),
        'Latency P95 (ms)': med_p95.values.round(1),
        'FPS': med_fps.values.round(1),
        'Throughput (kS/s)': (med_thr.values/1000.0).round(2),
        'Dropped (%)': med_drop.values.round(1),
        'CPU avg (%)': med_cpu_a.values.round(1),
        'CPU max (%)': med_cpu_m.values.round(1),
        'RSS avg (MB)': med_rss_a.values.round(0),
        'RSS max (MB)': med_rss_m.values.round(0),
    }).sort_values('workflow')

    summary.to_csv(os.path.join(out_dir, 'table1_summary.csv'), index=False)

    latex = summary.to_latex(index=False,
                             caption="RBciAD interactive performance (W1: Read→Display, W2: +Filter, W3: Stress).",
                             label="tab:rbciad_interactive",
                             column_format="lrrrrrrrrrrr")
    with open(os.path.join(out_dir, 'table1_latex.tex'),'w',encoding='utf-8') as f:
        f.write(latex)

# -------------- table 2 --------------
def build_table2(metrics_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    filt_path = os.path.join(metrics_dir, 'filters.csv')
    if not os.path.isfile(filt_path):
        # Rien à faire si pas d’événements filtre
        return
    df = pd.read_csv(filt_path)

    # Nettoyage duration
    if 'duration_s' in df.columns:
        df['duration_s'] = pd.to_numeric(df['duration_s'], errors='coerce')
    else:
        df['duration_s'] = np.nan

    # Méthode (ou fallback)
    method_col = 'method' if 'method' in df.columns else None
    df['group'] = df[method_col] if method_col else 'Filter'

    # Si aucun DONE, on écrit des CSV vides propres et on sort
    done = df[df['status'] == 'DONE'].copy()
    if done.empty:
        empty_by_run = pd.DataFrame(columns=['log','group','n','dur_med_s','dur_p95_s'])
        empty_by_run.to_csv(os.path.join(out_dir, 'table2_filters_by_run.csv'), index=False)

        empty_summary = pd.DataFrame(columns=['group','n','dur_med_s','dur_p95_s','fail_pct'])
        empty_summary.to_csv(os.path.join(out_dir, 'table2_filters_summary.csv'), index=False)

        with open(os.path.join(out_dir, 'table2_latex.tex'),'w',encoding='utf-8') as f:
            f.write("% No DONE filter events; table intentionally left blank.\n")
        return

    # Par run (log) et groupe
    by_run = (done
              .groupby(['log','group'])['duration_s']
              .agg(n='count', dur_med_s='median', dur_p95_s=p95_series)
              .reset_index())
    by_run['dur_med_s'] = pd.to_numeric(by_run['dur_med_s'], errors='coerce').round(3)
    by_run['dur_p95_s'] = pd.to_numeric(by_run['dur_p95_s'], errors='coerce').round(3)
    by_run.to_csv(os.path.join(out_dir, 'table2_filters_by_run.csv'), index=False)

    # Global par groupe + taux d’échec
    summary = (done
               .groupby(['group'])['duration_s']
               .agg(n='count', dur_med_s='median', dur_p95_s=p95_series)
               .reset_index())

    fails = (df.groupby('group')['status']
             .apply(lambda s: (s=='FAIL').mean()*100.0)
             .reset_index(name='fail_pct'))

    # Conversion numérique robuste AVANT arrondi
    summary['dur_med_s'] = pd.to_numeric(summary['dur_med_s'], errors='coerce')
    summary['dur_p95_s'] = pd.to_numeric(summary['dur_p95_s'], errors='coerce')
    fails['fail_pct']    = pd.to_numeric(fails['fail_pct'], errors='coerce')

    summary = summary.merge(fails, on='group', how='left')

    summary['dur_med_s'] = summary['dur_med_s'].round(3)
    summary['dur_p95_s'] = summary['dur_p95_s'].round(3)
    summary['fail_pct']  = pd.to_numeric(summary['fail_pct'], errors='coerce').round(1)

    summary = summary.sort_values('group')
    summary.to_csv(os.path.join(out_dir, 'table2_filters_summary.csv'), index=False)

    latex = summary.rename(columns={
        'group':'Step/Method','n':'N','dur_med_s':'Median (s)','dur_p95_s':'P95 (s)','fail_pct':'Fail (%)'
    }).to_latex(index=False,
                caption="External/filter step overhead (duration per method).",
                label="tab:rbciad_external_overhead",
                column_format="lrrrr")
    with open(os.path.join(out_dir, 'table2_latex.tex'),'w',encoding='utf-8') as f:
        f.write(latex)

# -------------- main --------------
def main():
    ap = argparse.ArgumentParser(description="Construit Tableaux 1 et 2 à partir des CSV de utils/metrics_eval.py")
    ap.add_argument('metrics_dir', help='Dossier contenant summary.csv / filters.csv / latencies.csv')
    ap.add_argument('--outdir', default='metrics_tables', help='Dossier de sortie')
    ap.add_argument('--no-rescan-raw', action='store_true',
                    help="Ne pas rouvrir les logs bruts pour throughput/dropped (laissera ces colonnes vides)")
    args = ap.parse_args()

    build_table1(args.metrics_dir, args.outdir, rescan_raw=not args.no_rescan_raw)
    build_table2(args.metrics_dir, args.outdir)
    print(f"OK. Tables écrites dans {args.outdir}")

if __name__ == '__main__':
    main()
