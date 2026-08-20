"""
filter_equivalence_v2.py
========================

Filter equivalence check — simplified version.

Instead of running the two platforms simultaneously against the same
signal, this version:

  1. Generates a deterministic 20-second test signal (test_signal.csv)
     using sim_eeg_lsl.py (with --no-pulse to avoid bursts that would
     contaminate the filter comparison).

  2. For each platform (RBciAD, OpenViBE):
     - You run the platform's W2 pipeline against the SAME source.
     - Capture the LSL output (BenchmarkOutput) to a CSV using this
       script's `capture` mode.

  3. Offline, compute the scipy reference (what a perfect Butterworth
     8-30 Hz order 4 should produce on the same signal).

  4. Compare each platform's capture to the reference via Pearson r.

Expected outcome: both platforms should have mean Pearson r >= 0.99
against the scipy reference. If so, they are equivalent.

Usage:
  # Step 1 & 2: launch sim_eeg_lsl.py with --no-pulse in one terminal.
  #             launch the platform's W2 pipeline in another.
  #             then run this in capture mode to record the output:
  python filter_equivalence_v2.py capture --out rbciad_W2_filtered.csv --duration 20
  python filter_equivalence_v2.py capture --out openvibe_W2_filtered.csv --duration 20

  # Step 3 & 4: once both captures are done, compare:
  python filter_equivalence_v2.py compare \\
      --rbciad rbciad_W2_filtered.csv \\
      --openvibe openvibe_W2_filtered.csv \\
      --out filter_equivalence.csv
"""

import argparse
import csv
import math
import sys
import time

import numpy as np
from pylsl import StreamInlet, local_clock, resolve_byprop


# ============ Capture mode ============

def capture_output(duration_s: float, out_csv: str,
                   stream_name: str = "BenchmarkOutput"):
    """Record a platform's filtered output to CSV."""
    print(f"[capture] Resolving '{stream_name}'...")
    streams = resolve_byprop("name", stream_name, timeout=15.0)
    if not streams:
        print(f"[capture] ERROR: stream '{stream_name}' not found.",
              file=sys.stderr)
        sys.exit(2)
    inlet = StreamInlet(streams[0], max_buflen=120, max_chunklen=0,
                        processing_flags=0)
    print(f"[capture] Connected. Recording {duration_s}s to {out_csv}")

    t_start = local_clock()
    t_end = t_start + duration_s
    all_samples = []
    all_ts = []

    while local_clock() < t_end:
        chunk, ts = inlet.pull_chunk(timeout=0.1, max_samples=256)
        if chunk:
            all_samples.extend(chunk)
            all_ts.extend(ts)
        time.sleep(0.005)

    n = len(all_samples)
    if n == 0:
        print("[capture] ERROR: no samples captured.", file=sys.stderr)
        sys.exit(2)

    n_ch = len(all_samples[0])
    print(f"[capture] Captured {n} samples, {n_ch} channels.")

    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        header = ["t"] + [f"ch{i+1}" for i in range(n_ch)]
        w.writerow(header)
        for ts_i, sample in zip(all_ts, all_samples):
            w.writerow([f"{ts_i:.6f}"] + [f"{v:.6f}" for v in sample])
    print(f"[capture] Wrote {out_csv}")


# ============ Compare mode ============

def _load_csv(path: str):
    """Load a capture CSV -> (timestamps, 2D array (N, n_ch))."""
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        n_ch = len(header) - 1
        ts = []
        data = []
        for row in r:
            if not row:
                continue
            ts.append(float(row[0]))
            data.append([float(x) for x in row[1:]])
    return np.array(ts), np.array(data)


def _rebuild_source_at_times(ts: np.ndarray,
                             sr: float = 250.0,
                             duration_s: float = 20.0):
    """
    Reconstruct what the input signal WAS at the LSL source timestamps.

    NOTE: sim_eeg_lsl.py with --no-pulse produces the following per
    channel (see generate_chunk):

      ch 0:                          noise
      ch c (c>=1):  sum_f sin(2 pi f t + c*pi/8) + noise

    where f in (10, 12) Hz.

    For filter equivalence, we ONLY need the DETERMINISTIC part
    (the sinusoidal base) because the noise differs between runs and
    would dominate the correlation. We recompute the base at the
    captured timestamps of each channel and compare to the filtered
    capture.
    """
    N_CHANNELS = 8
    SIN_FREQS = (10.0, 12.0)

    # Use relative time (starts at 0)
    if len(ts) == 0:
        return None
    t_rel = ts - ts[0]

    base = np.zeros((len(t_rel), N_CHANNELS), dtype=np.float64)
    for ch in range(1, N_CHANNELS):  # channel 0 stays at zero
        phase = ch * (math.pi / N_CHANNELS)
        for f in SIN_FREQS:
            base[:, ch] += np.sin(2 * math.pi * f * t_rel + phase)
    return base


def _scipy_reference(signal: np.ndarray, sr: float = 250.0) -> np.ndarray:
    """Apply a reference Butterworth BP 8-30 Hz order 4 using scipy."""
    from scipy.signal import butter, filtfilt
    b, a = butter(4, [8 / (sr / 2), 30 / (sr / 2)], btype="band")
    return filtfilt(b, a, signal, axis=0)


def _pearson_per_channel(a: np.ndarray, b: np.ndarray,
                         skip_start: int = 500):
    """Per-channel Pearson r on samples [skip_start:]."""
    a = a[skip_start:]
    b = b[skip_start:]
    n_ch = a.shape[1]
    rs = []
    for c in range(n_ch):
        ac = a[:, c] - a[:, c].mean()
        bc = b[:, c] - b[:, c].mean()
        denom = np.sqrt((ac * ac).sum()) * np.sqrt((bc * bc).sum())
        if denom < 1e-12:
            rs.append(float("nan"))
        else:
            rs.append(float((ac * bc).sum() / denom))
    return rs


def compare_platform(capture_path: str, platform_label: str,
                     sr: float = 250.0):
    """Compare one platform's capture to the scipy reference."""
    print(f"\n--- {platform_label} ---")
    print(f"Loading {capture_path}...")
    ts, filtered = _load_csv(capture_path)
    n, n_ch = filtered.shape
    print(f"Loaded {n} samples, {n_ch} channels.")

    # Rebuild deterministic source at these timestamps
    source = _rebuild_source_at_times(ts, sr=sr)
    if source is None:
        return None

    # Apply scipy reference filter on the source (skipping ch 0 which is
    # pure noise and has no deterministic content to compare)
    reference = _scipy_reference(source, sr=sr)

    # Compare per channel (skip ch 0 because it is all-noise)
    rs = _pearson_per_channel(filtered, reference, skip_start=500)
    rs_no_noise_ch = rs[1:]  # channels 1..7
    mean_r = float(np.nanmean(rs_no_noise_ch))
    min_r = float(np.nanmin(rs_no_noise_ch))
    print(f"Per-channel r (channels 1..7): "
          f"{[f'{x:.4f}' for x in rs_no_noise_ch]}")
    print(f"Mean r = {mean_r:.4f}   Min r = {min_r:.4f}")
    return {"platform": platform_label,
            "mean_r": mean_r,
            "min_r": min_r,
            "n_samples": n,
            "per_channel_r": rs_no_noise_ch}


def compare_mode(rbciad_csv: str, openvibe_csv: str, out_csv: str):
    """Run comparison for both platforms, write summary CSV."""
    results = []
    if rbciad_csv:
        r = compare_platform(rbciad_csv, "RBciAD")
        if r:
            results.append(r)
    if openvibe_csv:
        r = compare_platform(openvibe_csv, "OpenViBE")
        if r:
            results.append(r)

    if not results:
        print("\n[ERROR] No valid results.", file=sys.stderr)
        sys.exit(2)

    # Verdict
    print("\n=== VERDICT ===")
    all_pass = True
    for r in results:
        verdict = "PASS" if r["min_r"] >= 0.99 else "INVESTIGATE"
        print(f"  {r['platform']:<10}: mean r = {r['mean_r']:.4f}  "
              f"min r = {r['min_r']:.4f}  -> {verdict}")
        if r["min_r"] < 0.99:
            all_pass = False

    # Write CSV
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["platform", "mean_r", "min_r", "n_samples"])
        for r in results:
            w.writerow([r["platform"],
                        f"{r['mean_r']:.4f}",
                        f"{r['min_r']:.4f}",
                        r["n_samples"]])
    print(f"\n[compare] Wrote {out_csv}")

    if all_pass:
        print("\n[PASS] Filters are equivalent. You can proceed with the "
              "40-run benchmark.")
        sys.exit(0)
    else:
        print("\n[INVESTIGATE] At least one platform's filter diverges "
              "from the scipy reference. Check filter parameters "
              "(order, cutoffs, design).")
        sys.exit(1)


# ============ Main ============

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    p_cap = sub.add_parser("capture",
                           help="Record a platform's filtered output.")
    p_cap.add_argument("--out", required=True)
    p_cap.add_argument("--duration", type=float, default=20.0)
    p_cap.add_argument("--stream", default="BenchmarkOutput")

    p_cmp = sub.add_parser("compare",
                           help="Compare both captures to scipy reference.")
    p_cmp.add_argument("--rbciad", required=False, default=None)
    p_cmp.add_argument("--openvibe", required=False, default=None)
    p_cmp.add_argument("--out", default="filter_equivalence.csv")

    args = parser.parse_args()
    if args.mode == "capture":
        capture_output(args.duration, args.out, stream_name=args.stream)
    elif args.mode == "compare":
        compare_mode(args.rbciad, args.openvibe, args.out)


if __name__ == "__main__":
    main()