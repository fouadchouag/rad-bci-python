# tools/lsl_fake_eeg.py
# -*- coding: utf-8 -*-
"""
Fake EEG LSL stream (robuste & verbeux):
- name: FakeEEG
- type: EEG
- source_id: fakeeeg-001
- 8 channels, float32, 250 Hz
Usage:
    python tools/lsl_fake_eeg.py
    python tools/lsl_fake_eeg.py --sf 500 --nch 16 --name MyEEG --sid abc123 --chunk 64 --wait 3
"""
import argparse
import time
import math
import numpy as np

try:
    from pylsl import StreamInfo, StreamOutlet, cf_float32
except Exception as e:
    print("Install pylsl first: pip install pylsl")
    raise

def build_info(name: str, nch: int, sf: float, sid: str) -> StreamInfo:
    info = StreamInfo(name=name, type="EEG", channel_count=nch,
                      nominal_srate=sf, channel_format=cf_float32, source_id=sid)
    # Labels (métadonnées XDF)
    desc = info.desc()
    chans = desc.append_child("channels")
    labels = ["Fp1","Fp2","F3","F4","C3","C4","P3","P4"] + [f"Ch{i+1}" for i in range(max(0, nch-8))]
    for lab in labels[:nch]:
        ch = chans.append_child("channel")
        ch.append_child_value("label", lab)
        ch.append_child_value("unit", "uV")
        ch.append_child_value("type", "EEG")
    return info

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, default=250.0, help="sample rate (Hz)")
    ap.add_argument("--nch", type=int, default=8, help="number of channels")
    ap.add_argument("--name", type=str, default="FakeEEG", help="stream name")
    ap.add_argument("--sid", type=str, default="fakeeeg-001", help="source_id")
    ap.add_argument("--chunk", type=int, default=64, help="chunk size (samples)")
    ap.add_argument("--noise", type=float, default=0.05, help="noise level")
    ap.add_argument("--wait", type=float, default=0.0, help="wait for consumers seconds (0=don’t wait)")
    args = ap.parse_args()

    info = build_info(args.name, args.nch, args.sf, args.sid)
    outlet = StreamOutlet(info, chunk_size=args.chunk, max_buffered=600)

    # Infos d’en-tête utiles
    try:
        uid = info.uid()
    except Exception:
        uid = "?"
    print(f"Publishing LSL stream: {args.name}/EEG — {args.nch}ch @{args.sf:.1f}Hz "
          f"(sid={args.sid}, uid={uid}, chunk={args.chunk})")

    # (Optionnel) attendre un consommateur
    if args.wait and args.wait > 0:
        try:
            ok = outlet.wait_for_consumers(timeout=args.wait)
            print("Consumer status after wait:", "connected" if ok else "none")
        except Exception:
            pass

    t = 0
    phases = np.random.rand(args.nch) * 2*np.pi

    try:
        last_report = 0.0
        while True:
            tt = (t + np.arange(args.chunk)) / args.sf
            base = 0.7*np.sin(2*math.pi*10.0*tt)[:, None] + 0.3*np.sin(2*math.pi*20.0*tt)[:, None]
            chunk = np.repeat(base, args.nch, axis=1)
            chunk += 0.1*np.sin(2*math.pi*3.0*tt)[:, None] * np.sin(phases)[None, :]
            if args.noise > 0:
                chunk += args.noise * np.random.randn(args.chunk, args.nch)
            outlet.push_chunk(chunk.astype(np.float32))
            t += args.chunk

            # petit log sur la présence de consommateurs (toutes les ~5s)
            now = time.time()
            if now - last_report > 5.0:
                try:
                    print("have_consumers:", outlet.have_consumers())
                except Exception:
                    pass
                last_report = now

            # cadence ~temps réel
            time.sleep(args.chunk / args.sf)
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
