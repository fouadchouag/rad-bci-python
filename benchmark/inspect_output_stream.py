"""
inspect_output_stream.py
=========================

Listens to BenchmarkOutput (the platform's pipeline output) and reports
the peak amplitude on channel 0 over short windows. This tells us
whether pulses are still visible after bandpass filtering.

Usage:
    python inspect_output_stream.py --duration 20
"""

import argparse
import time

from pylsl import StreamInlet, local_clock, resolve_byprop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", default="BenchmarkOutput")
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args()

    print(f"[inspect] Resolving '{args.stream}'...")
    streams = resolve_byprop("name", args.stream, timeout=15.0)
    if not streams:
        print(f"[inspect] ERROR: stream '{args.stream}' not found.")
        return
    inlet = StreamInlet(streams[0], max_buflen=2, max_chunklen=25,
                        processing_flags=0)
    print(f"[inspect] Connected. Listening for {args.duration}s.")
    print(f"[inspect] Format: time_s | ch0 peak abs | ch0 max | samples in window")

    t_start = local_clock()
    t_end = t_start + args.duration

    # Running window
    win_duration = 0.5  # 500 ms windows
    next_report = t_start + win_duration
    ch0_peak_abs = 0.0
    ch0_max_signed = -1e9
    n_samples = 0
    global_max_peak = 0.0

    while local_clock() < t_end:
        chunk, ts = inlet.pull_chunk(timeout=0.0, max_samples=64)
        if chunk:
            for sample in chunk:
                v = sample[0]
                if abs(v) > ch0_peak_abs:
                    ch0_peak_abs = abs(v)
                if v > ch0_max_signed:
                    ch0_max_signed = v
                n_samples += 1
                if abs(v) > global_max_peak:
                    global_max_peak = abs(v)

        now = local_clock()
        if now >= next_report:
            elapsed = now - t_start
            print(f"  {elapsed:5.1f}s  |  peak_abs={ch0_peak_abs:8.3f}  "
                  f"max_signed={ch0_max_signed:8.3f}  n={n_samples}")
            ch0_peak_abs = 0.0
            ch0_max_signed = -1e9
            n_samples = 0
            next_report = now + win_duration

        time.sleep(0.005)

    print(f"\n[inspect] GLOBAL peak absolute amplitude on ch0: {global_max_peak:.3f}")
    print(f"[inspect] Our pulse threshold for detection: 50.0")
    if global_max_peak > 50.0:
        print("[inspect] -> pulses ARE visible at the output.")
    elif global_max_peak > 5.0:
        print("[inspect] -> pulses present but ATTENUATED below threshold "
              "(filter is smoothing them out).")
    else:
        print("[inspect] -> no obvious pulses. Either filter removes them "
              "completely, or LSL Export is not receiving the filter output.")


if __name__ == "__main__":
    main()
