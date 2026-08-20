# Inter-Platform Benchmark Protocol: RBciAD vs OpenViBE vs BCI2000

**Version:** 1.0
**Author:** F. Chouag, A. Khababa
**Repository:** https://github.com/fouadchouag/rad-bci-python
**Purpose:** Controlled comparative evaluation of three real-time EEG frameworks under identical input, hardware, and workload conditions.

---

## 1. Objective

Quantify the runtime overhead (latency, CPU, memory, throughput) of three representative open-source EEG frameworks — **RBciAD** (this work), **OpenViBE** (Renard et al., 2010), and **BCI2000** (Schalk et al., 2004) — when executing two equivalent real-time signal-processing pipelines on identical input.

This protocol is **not** intended to declare an overall winner. It aims to position RBciAD within the performance envelope of established reference platforms, under conditions that reviewers can reproduce.

---

## 2. Scope and Limitations (Stated Upfront)

**In scope:**
- Two pipelines (W1, W2), ten runs per pipeline per platform, 60 s per run.
- Four KPIs measurable through external, platform-agnostic instrumentation.
- A single hardware configuration (Intel Core i5, Windows 10, 8 GB RAM).

**Out of scope — explicitly acknowledged:**
- FPS is not measured across platforms (OpenViBE/BCI2000 visualizers do not expose framerate in a uniform way).
- TTFP and edit-to-first-frame latency are not measured across platforms (these depend on reactive-engine internals unique to RBciAD).
- Device-level acquisition latency (ADC overhead) is excluded — a synthetic LSL source is used to isolate framework overhead from hardware variability.
- This is a single-machine study; cross-machine generalization is left to future work.

---

## 3. Hardware and Software Environment

| Item | Value |
|------|-------|
| Machine | Dell Laptop, Intel Core i5 (8th gen), 1.7 GHz, 8 GB RAM |
| OS | Windows 10 (64-bit) |
| Power plan | High performance, AC power, sleep disabled |
| Antivirus / background apps | Suspended during runs |
| Python | 3.11 (for RBciAD and instrumentation scripts) |
| OpenViBE | version X.Y.Z (to be filled at install time) |
| BCI2000 | version X.Y.Z (to be filled at install time) |
| pylsl | latest stable |
| psutil | latest stable |

A `machine_info.json` is emitted before each session, capturing CPU load, free RAM, and system uptime as sanity baselines.

---

## 4. Common Data Source: Synthetic LSL Stream

A single Python script (`sim_eeg_lsl.py`, extended) serves as the common data source for all three platforms:

- **Channels:** 8
- **Sampling rate:** 250 Hz
- **Signal:** deterministic — sum of three sinusoids (10 Hz, 12 Hz, 20 Hz) + Gaussian noise (σ = 0.1, `np.random.seed(42)`)
- **Special marker:** every 2 s, channel 0 carries a 1 ms square pulse of amplitude 100. This pulse serves as the **latency probe** (see §6.1).
- **Duration:** 70 s per run (10 s warm-up + 60 s measurement)
- **Transport:** Lab Streaming Layer (LSL) outlet, type `EEG`, name `BenchmarkSource`.

The same outlet is consumed by all three platforms — eliminating driver or device-specific variability.

---

## 5. Pipelines Under Test

### 5.1 Pipeline W1 — Reader → Display

Minimal pipeline: acquire LSL stream and render.

| Platform | Implementation |
|----------|----------------|
| RBciAD | `LSL-Reader → EEGLiveDisplay` |
| OpenViBE | `Acquisition Client (LSL) → Signal Display` |
| BCI2000 | `LSLSource → DummyApplication (with visualization enabled)` |

### 5.2 Pipeline W2 — Reader → Filter → Display

Adds a 4th-order Butterworth bandpass filter (8–30 Hz).

| Platform | Implementation |
|----------|----------------|
| RBciAD | `LSL-Reader → EEGRawFilter (BP 8-30 Hz, order 4) → EEGLiveDisplay` |
| OpenViBE | `Acquisition Client (LSL) → Temporal Filter (Butterworth, BP 8-30 Hz, order 4) → Signal Display` |
| BCI2000 | `LSLSource → SpatialFilter (identity) → IIRBandpassFilter (BP 8-30 Hz, order 4) → DummyApplication` |

**Filter equivalence check:** a static 10 s chunk of signal is passed through each platform's filter and exported as CSV. The three outputs are cross-correlated offline; if Pearson r < 0.99, the filter configurations are adjusted until equivalence is reached. This step is mandatory and its results are reported in `filter_equivalence.csv`.

---

## 6. Instrumentation — External and Uniform

All instrumentation is **external** to the platform under test. No code injection into OpenViBE or BCI2000 is performed.

### 6.1 Latency Probe (end-to-end)

A separate Python script (`lsl_latency_probe.py`) runs concurrently with each platform:

1. It subscribes to the same source stream and records the timestamp `t_in` of each injected pulse.
2. The platform under test, after processing, re-publishes its output via a secondary LSL outlet (`BenchmarkOutput`).
   - **RBciAD:** via an added `LSL-Writer` node at the end of the graph.
   - **OpenViBE:** via `LSL Export` box.
   - **BCI2000:** via `LSLOutput` filter.
3. The probe records `t_out` of the same pulse on `BenchmarkOutput`.
4. Latency = `t_out - t_in` (monotonic clock, ns precision).

Approximately 30 pulses per 60 s run → **~300 latency samples per platform per workflow** (across 10 runs). Reported as **median** and **P95**.

**Rationale for pulse-based latency:** it does not rely on each platform's internal chunking model. It measures what the user actually experiences — from signal injection to signal availability downstream.

### 6.2 CPU and Memory (`psutil`)

A separate process (`external_benchmark.py`) identifies the platform's main process by PID (passed as CLI argument) and samples:

- `cpu_percent()` at 10 Hz
- `memory_info().rss` at 10 Hz

Reported as **average** and **max** over the 60 s measurement window (excluding 10 s warm-up).

### 6.3 Throughput

Throughput is **not** measured per-platform — it is **imposed** by the LSL source (8 channels × 250 Hz = 2 kSamples/s per channel, 16 kSamples/s across channels).

What is verified is **whether each platform sustains this rate without drops**: the probe checks that `BenchmarkOutput` receives at least 95% of the samples injected at the source. Platforms that fall below this threshold are flagged.

---

## 7. Experimental Schedule

### 7.1 Run structure

Each run follows:
1. Launch platform and load pipeline (manual, timed separately as "setup time" — informational only).
2. Start LSL source → wait 10 s warm-up.
3. Start `external_benchmark.py` and `lsl_latency_probe.py`.
4. Run 60 s measurement window.
5. Stop source, stop platform.
6. Export logs to `benchmark/runs/{platform}/{workflow}/run_{i}.csv`.

### 7.2 Randomization

To avoid thermal / warm-up bias, runs are interleaved **across platforms** within each session:

```
Session 1: RBciAD-W1-run1, OpenViBE-W1-run1, BCI2000-W1-run1,
           RBciAD-W1-run2, OpenViBE-W1-run2, BCI2000-W1-run2, ...
Session 2: same for W2
```

Between platform switches, a **2-minute cool-down** with all software closed.

### 7.3 Totals

- **2 workflows × 3 platforms × 10 runs = 60 runs**
- **60 × 60 s = 60 minutes of pure measurement** (plus overhead; total ~4–6 h of work over 1–2 days)

---

## 8. Output Files and Aggregation

```
benchmark/
├── sim_eeg_lsl.py              # shared LSL source with pulse probe
├── external_benchmark.py       # CPU/RSS sampler
├── lsl_latency_probe.py        # latency probe
├── aggregate_cross_platform.py # aggregator (produces Table 4)
├── filter_equivalence.csv      # Pearson r across 3 platforms' filters
├── machine_info.json           # hardware context
├── runs/
│   ├── RBciAD/{W1,W2}/run_*.csv
│   ├── OpenViBE/{W1,W2}/run_*.csv
│   └── BCI2000/{W1,W2}/run_*.csv
└── summary/
    ├── cross_platform_summary.csv   # median across 10 runs per (platform, workflow)
    └── figures/
        ├── fig_latency_boxplot.pdf
        ├── fig_cpu_rss_grouped.pdf
        └── fig_throughput.pdf
```

Aggregation per `(platform, workflow)` reports: **median**, **IQR**, **P95**, with Wilcoxon signed-rank tests for pairwise comparisons (RBciAD vs OpenViBE; RBciAD vs BCI2000).

---

## 9. Statistical Analysis

- **Descriptive:** median and IQR over 10 runs for each metric.
- **Inferential:** Wilcoxon signed-rank test (paired, since same machine and same source), α = 0.05, Holm-Bonferroni correction for multiple comparisons.
- **Effect size:** Cliff's delta (non-parametric, appropriate for small n).

**Interpretation rules set in advance** (to prevent post-hoc narratives):
- Latency difference < 10 ms is reported as "comparable" regardless of p-value.
- CPU difference < 5 pp is reported as "comparable".
- RSS difference < 50 MB is reported as "comparable".

These thresholds are set **before** looking at the data, as required by good statistical practice.

---

## 10. Reporting in the Manuscript

The benchmark results will populate:

- **New Table 4** — Inter-platform performance summary (median ± IQR for each KPI across 3 platforms × 2 workflows).
- **New Figure 15** — Grouped bar plots of latency, CPU, RSS across platforms.
- **New §5.4.1** — "Positioning against OpenViBE and BCI2000", 3–4 paragraphs, honest discussion including cases where RBciAD is comparable or slower (if any).

Language in the manuscript will avoid overclaiming. Expected phrasings:
- ✅ "RBciAD achieves latency comparable to OpenViBE (median X ms vs Y ms, p = Z)"
- ✅ "RBciAD uses more RAM than BCI2000, reflecting the Python runtime overhead"
- ❌ "RBciAD outperforms OpenViBE and BCI2000" (unless unambiguously supported by data)

---

## 11. Reproducibility

All code, raw logs, aggregated CSVs, and figure-generation scripts are committed under `benchmark/` in the RBciAD repository, tagged at a dedicated release (e.g., `v1.11.0-benchmark`), and archived on Zenodo with a separate DOI. The README in that folder contains exact commands to reproduce each step.

---

## 12. Timeline (Target: 7–10 days)

| Day | Task |
|-----|------|
| 1 | This protocol frozen + install OpenViBE + install BCI2000 |
| 2 | Build pipelines W1/W2 in all 3 platforms + filter equivalence check |
| 3 | Implement `sim_eeg_lsl.py` (with pulse) + `external_benchmark.py` + `lsl_latency_probe.py` |
| 4 | Pilot run (1 run per platform, full pipeline) — validate the chain |
| 5 | Execute session 1 (W1, 10×3 = 30 runs, interleaved) |
| 6 | Execute session 2 (W2, 10×3 = 30 runs, interleaved) |
| 7 | Aggregation + statistical analysis + figures |
| 8 | Draft §5.4.1 + Table 4 + Figure 15 |
| 9–10 | Review, sanity checks, archive on GitHub + Zenodo |

---

## 13. Changelog of Methodology Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| (today) | Drop W3 from cross-platform benchmark | W3's 80% overlap is RBciAD-specific; transposing it in OV/BCI2000 would require non-equivalent approximations |
| (today) | Drop FPS from cross-platform KPIs | OV/BCI2000 visualizers do not expose framerate uniformly |
| (today) | Drop TTFP and edit-latency from cross-platform KPIs | Reactive-engine metrics, no equivalent in OV/BCI2000 |
| (today) | Keep latency, CPU, RSS, sample-completeness | All measurable by external Python instrumentation |
| (today) | Use LSL as common transport | Eliminates device/driver variability |
| (today) | Use pulse-based latency probe | Independent of each platform's internal clock |
