# Performance

RBciAD is designed for low-latency, real-time EEG processing. This page documents performance characteristics and optimization tips.

## Key Metrics

| Metric | Target | Description |
|---|---|---|
| **TTFP** (Time To First Plot) | <250 ms | Latency from loading data to first visual output |
| **FPS** (Frames Per Second) | ≥50 | Rendering speed of visual nodes |
| **Inference latency** | <50 ms | Per-trial classification time for online BCI |
| **CPU usage** | <40% | During typical offline processing |
| **Memory** | <500 MB | For standard pipelines (128 channels, 10 min recording) |

## Benchmark Results

Measured on a mid-range laptop (Intel i7-12700H, 16 GB RAM, Windows 11):

| Pipeline | TTFP (ms) | FPS (avg) | CPU (%) | RAM (MB) |
|---|---|---|---|---|
| W1: Reader → Visualizer | 180 | 58 | 12 | 120 |
| W2: Reader → Filter → Visualizer | 210 | 55 | 18 | 140 |
| W3: Stress test (1s windows, 80% overlap) | 220 | 52 | 35 | 180 |
| TS-FBCSP Online Inference | 28 (per trial) | N/A | 8 | 200 |

## Optimization Tips

### For visualization

- Use **segment** output mode instead of **raw** for lower latency
- Enable **decimation** in visualizer nodes (skip frames for smoother display)
- Reduce the number of visible channels if FPS drops
- Close unused visualizer windows

### For offline processing

- Use **QThread-based** nodes (e.g., EEGRawFilter) for non-blocking execution
- Enable **background processing** for heavy computations
- Use `scipy.signal.sosfiltfilt` instead of `filtfilt` for better numerical stability

### For real-time inference

- Use **OAS shrinkage** covariance estimation (faster than Ledoit-Wolf)
- Pre-compute Riemannian mean during offline training (not at inference time)
- Keep the feature dimensionality reasonable (2277-D for 22ch TS-FBCSP is typical)
- Avoid unnecessary data copies between nodes

### Memory

- Use **lazy loading / memmap** for large EEG files (supported by EEGUniversalReader)
- Process data in chunks rather than loading everything into memory
- The ring-buffer in visualizers limits memory usage for continuous streams

## Measuring Performance

RBciAD includes built-in metrics hooks:

1. Press **F9** to start recording metrics
2. Perform your pipeline operations
3. Press **F9** again to stop
4. Metrics are saved to `runs/` as JSON files
5. Analyze with:
   ```bash
   python utils/metrics_eval.py runs --outdir metrics_results
   python utils/build_tables_from_metrics.py metrics_results --outdir tables
   ```

### Available metrics

- **TTFP**: Time from data load to first plot
- **FPS**: Frames per second (with p50/p95 statistics)
- **CPU/RSS**: CPU usage and memory (average/max)
- **Latency**: PARAM_CHANGE → FRAME delivery time
- **Dropped frames**: Count and percentage
- **Filter duration**: Per-filter processing time (p50/p95)

## Reproducing Benchmarks

See `benchmark/BENCHMARK_PROTOCOL.md` for the full experimental protocol. Quick start:

```bash
cd benchmark
python parse_events_min.py --input runs/ --output results/
```

The benchmark compares RBciAD against OpenViBE and BCI2000 on identical pipelines.
