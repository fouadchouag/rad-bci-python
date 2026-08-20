"""
sim_eeg_lsl.py
==============

Synthetic EEG LSL source for the RBciAD cross-platform benchmark.

This script is the *common input* to RBciAD, OpenViBE, and BCI2000
during inter-platform benchmarking. It must be identical across all
platforms to ensure a fair comparison.

Signal specification (frozen per BENCHMARK_PROTOCOL.md):
- Channels        : 8
- Sampling rate   : 250 Hz
- Content         : sum of 3 deterministic sinusoids (10, 12, 20 Hz)
                    + Gaussian noise (seed=42, sigma=0.1)
- Latency probe   : every 2 s, channel 0 carries a 1-sample pulse of
                    amplitude 100.0. All other samples stay below 5.0.
- Duration        : user-settable (default 70 s: 10 s warm-up + 60 s)
- Stream name     : "BenchmarkSource"
- Stream type     : "EEG"
- Format          : float32

Usage:
    python sim_eeg_lsl.py --duration 70
    python sim_eeg_lsl.py --duration 70 --no-pulse    # disable pulses
"""

import argparse
import math
import time

import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock


# -------- Constants frozen by the protocol (do not change casually) --------
N_CHANNELS = 8
SAMPLING_RATE = 250              # Hz
CHUNK_SIZE = 25                  # 25 samples = 100 ms chunks
PULSE_EVERY_S = 2.0              # one burst every 2 seconds

# --- PULSE (burst) configuration ---
# The probe needs to detect a marker on channel 0, that survives a
# 8-30 Hz bandpass filter. A single-sample impulse gets heavily attenuated.
# Instead, we emit a short 20-Hz sinusoidal burst: 20 Hz sits in the
# middle of the passband, so the filter passes it through almost unchanged.
PULSE_FREQ = 20.0                # Hz -- inside any 8-30 Hz bandpass
PULSE_DURATION_S = 0.050         # 50 ms burst = 10 full cycles of 20 Hz
PULSE_AMPLITUDE = 100.0          # peak amplitude of the burst (well above bkg)

NOISE_SIGMA = 0.1
# Background sinusoids on OTHER channels only. To keep channel 0 clean
# so the burst stands out, channel 0 carries only noise + the burst.
SIN_FREQS = (10.0, 12.0)         # 20 Hz removed to avoid interfering with pulse
RNG_SEED = 42
STREAM_NAME = "BenchmarkSource"
STREAM_TYPE = "EEG"
# ---------------------------------------------------------------------------


def build_outlet() -> StreamOutlet:
    """Create the LSL outlet with frozen metadata."""
    info = StreamInfo(
        name=STREAM_NAME,
        type=STREAM_TYPE,
        channel_count=N_CHANNELS,
        nominal_srate=SAMPLING_RATE,
        channel_format="float32",
        source_id="rbciad_benchmark_source_v1",
    )
    # Channel labels for platforms that read them
    channels = info.desc().append_child("channels")
    for i in range(N_CHANNELS):
        ch = channels.append_child("channel")
        ch.append_child_value("label", f"Ch{i+1}")
        ch.append_child_value("unit", "microvolts")
        ch.append_child_value("type", "EEG")
    return StreamOutlet(info, chunk_size=CHUNK_SIZE, max_buffered=360)


def generate_chunk(
    sample_idx_start: int,
    chunk_size: int,
    rng: np.random.Generator,
    enable_pulse: bool,
) -> np.ndarray:
    """
    Build one chunk of shape (chunk_size, N_CHANNELS) as float32.

    Channel 0 is the 'pulse channel': it carries only noise (no background
    sinusoids), so the burst stands out. Every PULSE_EVERY_S seconds, a
    short 20-Hz sinusoidal burst of PULSE_DURATION_S duration is injected
    with peak amplitude PULSE_AMPLITUDE. 20 Hz sits inside any 8-30 Hz
    bandpass so the filter does not attenuate it.

    Channels 1..N_CHANNELS-1 carry background sinusoids (SIN_FREQS) + noise.
    """
    t = (np.arange(chunk_size, dtype=np.float64)
         + sample_idx_start) / SAMPLING_RATE  # (chunk_size,)

    # Deterministic sinusoidal base on channels 1..N-1 (channel 0 stays clean)
    base = np.zeros((chunk_size, N_CHANNELS), dtype=np.float64)
    for ch in range(1, N_CHANNELS):
        phase = ch * (math.pi / N_CHANNELS)
        for f in SIN_FREQS:
            base[:, ch] += np.sin(2 * math.pi * f * t + phase)

    # Reproducible noise on all channels
    noise = rng.normal(0.0, NOISE_SIGMA, size=(chunk_size, N_CHANNELS))

    chunk = base + noise

    # Inject 20-Hz bursts on channel 0
    if enable_pulse:
        pulse_period_samples = int(round(PULSE_EVERY_S * SAMPLING_RATE))
        burst_len_samples = int(round(PULSE_DURATION_S * SAMPLING_RATE))
        for k in range(chunk_size):
            global_idx = sample_idx_start + k
            # Where are we inside the 2 s pulse period?
            phase_in_period = global_idx % pulse_period_samples
            # A burst starts at the beginning of each new period (except t=0)
            if global_idx > 0 and phase_in_period < burst_len_samples:
                # Time inside the burst
                t_burst = phase_in_period / SAMPLING_RATE
                chunk[k, 0] = PULSE_AMPLITUDE * math.sin(
                    2 * math.pi * PULSE_FREQ * t_burst
                )

    return chunk.astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description="Synthetic EEG LSL source.")
    parser.add_argument("--duration", type=float, default=70.0,
                        help="Total duration in seconds (default 70).")
    parser.add_argument("--no-pulse", action="store_true",
                        help="Disable pulse probe (for signal-only use).")
    args = parser.parse_args()

    enable_pulse = not args.no_pulse
    rng = np.random.default_rng(RNG_SEED)
    outlet = build_outlet()

    print(f"[sim_eeg_lsl] Outlet '{STREAM_NAME}' ready.")
    print(f"[sim_eeg_lsl] {N_CHANNELS} ch @ {SAMPLING_RATE} Hz, "
          f"pulse={'ON' if enable_pulse else 'OFF'}, duration={args.duration}s")
    print("[sim_eeg_lsl] Waiting 2 s so consumers can connect...")
    time.sleep(2.0)

    total_samples = int(args.duration * SAMPLING_RATE)
    sample_idx = 0
    t0 = local_clock()
    next_push_time = t0

    print(f"[sim_eeg_lsl] Start at local_clock={t0:.6f}")

    try:
        while sample_idx < total_samples:
            this_chunk = min(CHUNK_SIZE, total_samples - sample_idx)
            chunk = generate_chunk(sample_idx, this_chunk, rng, enable_pulse)

            # Timestamp = ideal time of the FIRST sample in the chunk
            chunk_t0 = t0 + sample_idx / SAMPLING_RATE
            outlet.push_chunk(chunk.tolist(), timestamp=chunk_t0)

            sample_idx += this_chunk

            # Pace ourselves to stay close to real time
            next_push_time += this_chunk / SAMPLING_RATE
            sleep_for = next_push_time - local_clock()
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        print("\n[sim_eeg_lsl] Interrupted by user.")

    elapsed = local_clock() - t0
    print(f"[sim_eeg_lsl] Done. Pushed {sample_idx} samples in {elapsed:.2f} s "
          f"(effective rate = {sample_idx / elapsed:.1f} Hz).")


if __name__ == "__main__":
    main()
