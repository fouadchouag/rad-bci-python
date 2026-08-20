"""
lsl_latency_probe.py
====================

End-to-end latency probe for the RBciAD cross-platform benchmark.

Listens to TWO LSL streams simultaneously:
  - BenchmarkSource  : raw input stream produced by sim_eeg_lsl.py
  - BenchmarkOutput  : output stream produced by the platform under test
                       (RBciAD / OpenViBE / BCI2000), after its pipeline

Detects pulses (channel 0, amplitude > 50) on both streams and records
the round-trip latency for each detected pulse:

    latency = t_out(pulse_k) - t_in(pulse_k)

Where t_in and t_out are local_clock() timestamps taken the moment this
probe *receives* each pulse — so the same clock is used for both ends,
eliminating any dependence on the platform's internal clock.

Output CSV columns:
    pulse_idx, t_in_s, t_out_s, latency_s, latency_ms

Usage:
    python lsl_latency_probe.py --out runs/RBciAD/W2/latency_run1.csv --duration 70
"""

import argparse
import csv
import time
from collections import deque

from pylsl import StreamInlet, local_clock, resolve_byprop


SOURCE_STREAM = "BenchmarkSource"
OUTPUT_STREAM = "BenchmarkOutput"
PULSE_THRESHOLD = 50.0   # pulse is 100, noise+signal stays well below 50
PULSE_CHANNEL = 0
MATCH_WINDOW_S = 5.0     # max plausible round-trip (safeguard)


def resolve_inlet(name: str, timeout: float = 10.0) -> StreamInlet:
    """Resolve an LSL stream by name with a clear error if absent."""
    print(f"[probe] Resolving stream '{name}' (timeout {timeout}s)...")
    streams = resolve_byprop("name", name, timeout=timeout)
    if not streams:
        raise RuntimeError(
            f"LSL stream '{name}' not found within {timeout}s. "
            f"Make sure the source (sim_eeg_lsl.py) or the platform "
            f"output (BenchmarkOutput) is running."
        )
    # Small buffer + no post-processing -> keep probe clock pure
    return StreamInlet(streams[0], max_buflen=2, max_chunklen=25, processing_flags=0)


def detect_pulse_events(chunk, timestamps, state):
    """
    Find rising-edge pulse events in a chunk.

    Returns list of (local_receive_time, pulse_index) for each detected
    pulse. The 'state' dict tracks 'above' flag and 'last_pulse_idx'
    across calls so we only fire once per rising edge.
    """
    events = []
    if chunk is None:
        return events
    # chunk is list of lists: [sample][channel]
    for i, sample in enumerate(chunk):
        v = sample[PULSE_CHANNEL]
        if v > PULSE_THRESHOLD and not state["above"]:
            # Rising edge detected at sample i of this chunk
            t_recv = timestamps[i] if timestamps else local_clock()
            # But we want the LOCAL CLOCK at reception, not the source TS.
            # We approximate reception by local_clock() of this call;
            # timestamps[] carries the producer's timestamp.
            events.append((local_clock(), state["next_pulse_idx"]))
            state["next_pulse_idx"] += 1
            state["above"] = True
        elif v <= PULSE_THRESHOLD and state["above"]:
            state["above"] = False
    return events


def run_probe(duration_s: float, output_csv: str, require_output: bool = True):
    src_inlet = resolve_inlet(SOURCE_STREAM, timeout=15.0)

    if require_output:
        out_inlet = resolve_inlet(OUTPUT_STREAM, timeout=15.0)
    else:
        out_inlet = None
        print("[probe] NOTE: --source-only -> only input pulses will be logged.")

    # Per-stream detection state
    src_state = {"above": False, "next_pulse_idx": 0}
    out_state = {"above": False, "next_pulse_idx": 0}

    # Ring of recent input events, to match with output events by order
    src_events = deque()       # list of (t_in, pulse_idx)
    out_events = deque()       # list of (t_out, pulse_idx)
    matched = []               # list of (pulse_idx, t_in, t_out, latency)

    t_start = local_clock()
    t_end = t_start + duration_s

    print(f"[probe] Recording for {duration_s}s starting at "
          f"local_clock={t_start:.3f}")

    while local_clock() < t_end:
        # --- Read source ---
        chunk, timestamps = src_inlet.pull_chunk(timeout=0.0,
                                                 max_samples=64)
        if chunk:
            for (t_recv, idx) in detect_pulse_events(chunk, timestamps,
                                                    src_state):
                src_events.append((t_recv, idx))

        # --- Read output ---
        if out_inlet is not None:
            chunk_o, ts_o = out_inlet.pull_chunk(timeout=0.0,
                                                 max_samples=64)
            if chunk_o:
                for (t_recv, idx) in detect_pulse_events(chunk_o, ts_o,
                                                        out_state):
                    out_events.append((t_recv, idx))

        # --- Match pulses in order ---
        while src_events and out_events:
            t_in, idx_in = src_events[0]
            t_out, idx_out = out_events[0]
            # If an output pulse is older than an input pulse, drop it
            # (race at startup). Otherwise pair in FIFO order.
            if t_out < t_in - MATCH_WINDOW_S:
                out_events.popleft()
                continue
            # Pair them
            latency = t_out - t_in
            if latency < 0 or latency > MATCH_WINDOW_S:
                # Unrealistic -> discard the older one and retry
                if t_in < t_out:
                    src_events.popleft()
                else:
                    out_events.popleft()
                continue
            matched.append((idx_in, t_in, t_out, latency))
            src_events.popleft()
            out_events.popleft()

        time.sleep(0.005)  # ~5 ms polling, light on CPU

    # Final flush: any unmatched source events stay unmatched (no output yet)
    n_unmatched = len(src_events)
    if n_unmatched:
        print(f"[probe] WARNING: {n_unmatched} input pulses had no matching "
              f"output (pipeline may have dropped them or shut down early).")

    # In source-only mode, we have no output stream to pair against. Write
    # the detected source pulses to the CSV so the user sees a non-empty
    # file. latency fields are NaN in that case.
    if out_inlet is None:
        with open(output_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pulse_idx", "t_in_s", "t_out_s",
                        "latency_s", "latency_ms"])
            for (t_in, idx) in list(src_events):
                w.writerow([idx, f"{t_in:.6f}", "", "", ""])
        print(f"[probe] SOURCE-ONLY mode: logged {len(src_events)} detected "
              f"source pulses (no latency computed).")
        return

    # Write CSV (full mode with both source and output)
    with open(output_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pulse_idx", "t_in_s", "t_out_s",
                    "latency_s", "latency_ms"])
        for idx, t_in, t_out, lat in matched:
            w.writerow([idx, f"{t_in:.6f}", f"{t_out:.6f}",
                        f"{lat:.6f}", f"{lat*1000:.3f}"])

    print(f"[probe] Wrote {len(matched)} matched pulses to {output_csv}")
    if matched:
        lats = sorted(l for (_, _, _, l) in matched)
        n = len(lats)
        p50 = lats[n // 2] * 1000
        p95 = lats[int(n * 0.95)] * 1000 if n > 1 else lats[0] * 1000
        mn = lats[0] * 1000
        mx = lats[-1] * 1000
        print(f"[probe] Latency stats (ms): "
              f"min={mn:.1f}  P50={p50:.1f}  P95={p95:.1f}  max={mx:.1f}")


def main():
    parser = argparse.ArgumentParser(description="LSL end-to-end latency probe.")
    parser.add_argument("--out", required=True, help="Output CSV path.")
    parser.add_argument("--duration", type=float, default=70.0,
                        help="Probe duration in seconds (default 70).")
    parser.add_argument("--source-only", action="store_true",
                        help="Log source pulses only (no output stream). "
                             "Useful to sanity-check the source.")
    args = parser.parse_args()

    run_probe(
        duration_s=args.duration,
        output_csv=args.out,
        require_output=not args.source_only,
    )


if __name__ == "__main__":
    main()
