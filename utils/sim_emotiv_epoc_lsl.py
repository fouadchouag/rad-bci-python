# utils/sim_emotiv_epoc_lsl.py
# -*- coding: utf-8 -*-
import argparse
import time
import math
import numpy as np

try:
    from pylsl import StreamInfo, StreamOutlet, local_clock
except Exception as e:
    raise SystemExit(f"[ERROR] pylsl requis: {e}\n> pip install pylsl")

EMOTIV_14 = ["AF3","F7","F3","FC5","T7","P7","O1","O2","P8","T8","FC6","F4","F8","AF4"]

def make_info(name, uid, fs, ch_names):
    info = StreamInfo(name=name, type="EEG", channel_count=len(ch_names),
                      nominal_srate=fs, channel_format="float32", source_id=uid)
    # labels XML
    desc = info.desc().append_child("channels")
    for lab in ch_names:
        ch = desc.append_child("channel")
        ch.append_child_value("label", lab)
        ch.append_child_value("type", "EEG")
        ch.append_child_value("unit", "uV")
    return info

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Emotiv-EPOC-Sim", help="Nom du flux LSL")
    ap.add_argument("--uid", default="emotiv-epoc-sim-001", help="source_id")
    ap.add_argument("--fs", type=float, default=128.0, help="Hz (EPOC ~128)")
    ap.add_argument("--chunk", type=int, default=16, help="échantillons par chunk")
    ap.add_argument("--amp", type=float, default=50.0, help="amplitude uV")
    ap.add_argument("--noise", type=float, default=5.0, help="bruit uV RMS")
    args = ap.parse_args()

    fs = float(args.fs)
    dt = 1.0 / fs
    n_ch = 14
    ch_names = EMOTIV_14

    info = make_info(args.name, args.uid, fs, ch_names)
    outlet = StreamOutlet(info, chunk_size=args.chunk, max_buffered=60)

    print(f"[Sim] LSL up: name={args.name} type=EEG ch={n_ch} fs={fs} chunk={args.chunk}")
    phase = np.random.rand(n_ch) * 2*np.pi
    t0 = local_clock()
    t  = 0.0

    try:
        while True:
            # génère un chunk (n_samples, n_channels)
            n = args.chunk
            times = t + np.arange(n) * dt
            # alpha ~10 Hz + légère autre composante + bruit
            sig = []
            for c in range(n_ch):
                f1 = 10.0 + (c % 3) * 0.5
                f2 = 6.0 + (c % 5) * 0.3
                s  = (args.amp * 0.7)*np.sin(2*np.pi*f1*times + phase[c]) \
                   + (args.amp * 0.3)*np.sin(2*np.pi*f2*times + 0.3*phase[c]) \
                   + np.random.normal(0.0, args.noise, size=n)
                sig.append(s.astype(np.float32))
            chunk = np.ascontiguousarray(np.stack(sig, axis=1), dtype=np.float32)  # (n, ch)

            outlet.push_chunk(chunk)
            t += n * dt

            # temporisation temps réel
            now = local_clock()
            target = t0 + t
            to_sleep = max(0.0, target - now)
            if to_sleep > 0:
                time.sleep(to_sleep)
    except KeyboardInterrupt:
        print("\n[Sim] Stopped.")

if __name__ == "__main__":
    main()
