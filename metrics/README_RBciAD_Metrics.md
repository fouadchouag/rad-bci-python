# RBciAD — Metrics & UX Thresholds (v2)

This package ships a small **CLI** to generate publication‑ready **tables** and **figures** from
RBciAD performance logs, with **UX/UI thresholds** overlaid for reviewer‑friendly context.

## 1) Quick start

```bash
# Aggregated metrics CSV -> table + charts (+ optional multipanel)
python rbciad_metrics_cli.py --metrics /path/to/metrics.csv --outdir out --multipanel

# Event logs (PARAM_CHANGE/FRAME) -> recompute latencies (+ optional timeline)
python rbciad_metrics_cli.py --events run1.csv run2.csv --outdir out_events --timeline
```

**Input (metrics.csv) columns** (example):
```
workflow,TTFP (s),Latency P50 (ms),Latency P95 (ms),FPS,Throughput (kS/s),Dropped (%),CPU avg (%),CPU max (%),RSS avg (MB),RSS max (MB)
W1, ...
W2, ...
W3, ...
```
> `Throughput (kS/s)` is interpreted as **kSamples/s across channels** (recommended label in the paper).

**Input (events) formats** (either one):
- `ts_us,ev,payload` (timestamp in microseconds)
- `timestamp,event,...` (seconds or microseconds; auto‑convert to µs if max(timestamp) < 1e6)

Recognized event names:
- **TTFP**: last `START_TTFP` → first `FIRST_FRAME`/`FRAME`/`RENDER_FRAME`
- **Interaction latency**: each `PARAM_CHANGE` → **next** frame (in ms)

---

## 2) Outputs

### When using `--metrics`
- `RBciAD_metrics_augmented.csv`: original table **+ Δ% vs W1**
- Charts (PNG), each with appropriate **threshold overlays**:
  - `chart_latency_with_thresholds.png`: Latency **P50/P95** with lines at **100/200/500/1000 ms**
  - `chart_ttfp_with_thresholds.png`: TTFP with **0.1/1/10 s** landmarks
  - `chart_fps_with_thresholds.png`: FPS with **60/30 fps** markers
  - `chart_throughput.png`: Throughput (kSamples/s across channels)
  - `chart_dropped_with_target.png`: Dropped frames with **5%** acceptance target (engineering)
  - `chart_cpu.png`: CPU avg/max
  - `chart_memory.png`: RSS avg/max
- (Optional) `--multipanel` → **RBciAD_Figure_Multipanel.png** (stitches the key charts into a single figure)

### When using `--events`
- `events_latency_from_events_summary.csv`: count, **P50**, **P95**, **TTFP**
- `events_latency_pairs.csv`: all **PARAM_CHANGE → first FRAME** latencies (one row per change)
- `events_latency_hist.png`: histogram with **100/200/500/1000 ms** reference lines
- (Optional) `--timeline` → `events_timeline.png`: **Timeline** showing PARAM_CHANGE markers (^), FRAME markers (•) and latency labels

---

## 3) Why these thresholds? (UX references)

- **0.1 s / 1 s / 10 s**: classic HCI response‑time limits for **instantaneous**, **seamless**, and **attention‑span** bounds (Nielsen Norman Group).  
  https://www.nngroup.com/articles/response-times-3-important-limits/  
  https://www.nngroup.com/articles/powers-of-10-time-scales-in-ux/
- **INP (Interaction to Next Paint)**: **≤ 200 ms (good)**, **200–500 ms (needs improvement)**, **> 500 ms (poor)**, typically evaluated at the **75th percentile** (web.dev / Google).  
  https://web.dev/articles/inp  
  https://web.dev/articles/optimize-inp
- **60 fps** target (≈ **16.7 ms**/frame) for animation smoothness; avoid **jank**/**long frames** (web.dev/RAIL).  
  https://web.dev/articles/rail  
  https://web.dev/articles/rendering-performance  
  https://web.dev/articles/speed-rendering

> **EEG context**: RBciAD’s trace display is **windowed** and prioritizes **latency to apply parameter changes** over cinematic framerates. The paper therefore emphasizes **interaction latency (P95)** as the primary UX KPI (target **< 100 ms**), while reporting FPS transparently.

---

## 4) Repro steps for the paper

1. Export your **aggregated metrics** to CSV (columns above).  
2. Run the CLI with `--metrics` to generate the **augmented table** and **charts** (+ use `--multipanel` for the stitched figure).  
3. (Optional) Pass event logs with `--events` to **recompute** latencies (PARAM_CHANGE→FRAME) for auditability and to produce **timeline/histogram**.  
4. Insert the PNGs and the augmented CSV into the paper’s **Table 1 / Figure 6**, and reference the UX thresholds as above.

---

## 5) Changelog
- **v2**: add `--multipanel` (stitched figure) and `--timeline` (timeline chart from events); export per‑change latency CSV.
- **v1**: base metrics processing, Δ% vs W1, charts with UX thresholds.

---

© 2025 RBciAD.
