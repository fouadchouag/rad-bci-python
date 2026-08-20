# Cross-Platform Benchmark: RBciAD vs OpenViBE vs BCI2000

This folder contains the instrumentation and protocol to compare
**RBciAD** against **OpenViBE** and **BCI2000** under identical input,
hardware, and workload conditions.

**Protocol:** see `BENCHMARK_PROTOCOL.md` in this folder (read it first).

---

## 1. Installation

### 1.1 Python dependencies (on the benchmarking machine)

```bash
pip install pylsl psutil numpy scipy
```

### 1.2 OpenViBE
Download from https://openvibe.inria.fr/downloads/ (Windows installer).
You need a version that ships with the `LSL Acquisition Client` box
(any 3.x release works).

### 1.3 BCI2000
Download from https://www.bci2000.org/mediawiki/index.php/Downloads.
You need the `LSLSource` module and the `SignalProcessing` filter set.

---

## 2. Files in this folder

| File | Role |
|------|------|
| `BENCHMARK_PROTOCOL.md`      | Frozen experimental protocol |
| `sim_eeg_lsl.py`             | Synthetic LSL source (common input) |
| `lsl_latency_probe.py`       | End-to-end latency probe |
| `external_benchmark.py`      | CPU/RSS sampler via psutil |
| `run_benchmark_session.py`   | Orchestrator for one trial |
| `aggregate_cross_platform.py`| Aggregator (produces Table 4) |
| `runs/`                      | Raw per-trial CSVs (created by runs) |
| `summary/`                   | Aggregated results + pairwise tests |

---

## 3. Pre-flight: sanity check the source

Before touching any platform, verify the source works alone:

```bash
# Terminal 1
python sim_eeg_lsl.py --duration 15

# Terminal 2 (at the same time)
python lsl_latency_probe.py --out sanity.csv --duration 12 --source-only
```

You should see roughly 6 pulses detected over 12 s, all from the source
stream. If not, LSL is not working on your machine — fix that before
benchmarking anything.

---

## 4. One trial, step by step

Each platform needs a small one-time setup:
- In the platform's GUI, build pipeline **W1** (Reader → Display) and
  pipeline **W2** (Reader → BP 8–30 Hz → Display).
- Add an **LSL output** at the end of each pipeline so the probe can
  read the processed signal:
  - **RBciAD**: add an `LSL-Writer` node with stream name `BenchmarkOutput`.
  - **OpenViBE**: add an `LSL Export` box named `BenchmarkOutput`.
  - **BCI2000**: configure `LSLOutput` with `OutputStreamName=BenchmarkOutput`.
- Save these pipelines (names suggested: `bench_W1.xml`, `bench_W2.xml` etc.).

Then for each trial:

```bash
# 1. Open the platform and load the pipeline. Do NOT start it yet.
#    Note the PID of the platform process (Task Manager on Windows).

# 2. Launch the orchestrator:
python run_benchmark_session.py \
    --platform RBciAD --workflow W2 --run-idx 1 \
    --platform-pid 12345 --duration 70

# 3. When you see "PRESS PLAY IN THE PLATFORM NOW", press Play.

# 4. Wait ~70 s; the script writes
#    runs/RBciAD/W2/latency_run1.csv
#    runs/RBciAD/W2/cpu_run1.csv

# 5. STOP the platform pipeline. Cool down 2 minutes. Repeat for the
#    NEXT platform in the interleaving schedule.
```

---

## 5. Full interleaved schedule (recommended)

Follow `BENCHMARK_PROTOCOL.md §7.2`. Two sessions of 30 trials each:

**Session 1 (workflow W1, ~3 h):**
```
W1 run1: RBciAD, OpenViBE, BCI2000
W1 run2: RBciAD, OpenViBE, BCI2000
...
W1 run10: RBciAD, OpenViBE, BCI2000
```

**Session 2 (workflow W2, ~3 h):** same pattern for W2.

Between platforms: 2-minute cool-down (close the platform GUI).

---

## 6. Aggregation

When all trials are done:

```bash
python aggregate_cross_platform.py --runs-dir runs --out-dir summary
```

This produces:
- `summary/cross_platform_summary.csv` — the core of Table 4.
- `summary/pairwise_tests.csv` — Wilcoxon signed-rank tests,
  Holm-Bonferroni adjusted.

---

## 7. Sanity checks BEFORE trusting the results

1. **Latency sample count.** At 2 s/pulse × 60 s = ~30 pulses per run.
   If `n_pulses` in the summary is much lower for one platform, that
   platform is dropping pulses — investigate before reporting.
2. **Filter equivalence.** The one-time `filter_equivalence.csv` check
   (see protocol §5.2) must show Pearson r ≥ 0.99 across all three
   platforms' filters. If not, your filters are not comparable and the
   W2 comparison is invalid.
3. **CPU normalization.** `external_benchmark.py` normalizes CPU by
   the number of logical cores, so 100% = "fully saturating one core".
   Do not compare with raw `cpu_percent()` from elsewhere.
4. **Baseline load.** If CPU > 30% idle on your machine with nothing
   running, close background apps before benchmarking.

---

## 8. What goes into the manuscript

- A single new **Table 4** ("Inter-platform performance") from
  `summary/cross_platform_summary.csv`.
- A single new **Figure 15** (latency boxplots + CPU/RSS bars) —
  plotting script not provided here (you can use the CSV with your
  usual workflow, e.g. matplotlib or pandas).
- A single new subsection **§5.4.1** ("Positioning against OpenViBE
  and BCI2000") — text template will be drafted separately.

Do not overclaim: the protocol sets "comparability thresholds"
(latency < 10 ms, CPU < 5 pp, RSS < 50 MB) that must be respected in
the language of the paper.
