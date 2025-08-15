# utils/lsl_probe.py
# -*- coding: utf-8 -*-
import argparse
import numpy as np

try:
    from pylsl import resolve_streams, resolve_byprop, StreamInlet
except Exception as e:
    raise SystemExit(f"[ERROR] pylsl: {e}")

def channel_labels(info):
    try:
        chs = info.desc().child("channels")
        labs = []
        ch = chs.first_child()
        while ch.name() == "channel":
            labs.append(ch.child_value("label") or f"ch{len(labs)+1}")
            ch = ch.next_sibling()
        return labs
    except Exception:
        return []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="EEG", help="type LSL à chercher (EEG, Marker, ...)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--n", type=int, default=3, help="nb chunks à lire")
    ap.add_argument("--max-samples", type=int, default=32)
    ap.add_argument("--list", action="store_true", help="lister tous les flux")
    args = ap.parse_args()

    if args.list:
        alls = resolve_streams(args.timeout)
        if not alls:
            print("[INFO] Aucun flux.")
            return
        print(f"[INFO] {len(alls)} flux:")
        for s in alls:
            print(f" - name={s.name()} type={s.type()} ch={s.channel_count()} fs={s.nominal_srate()} id={s.source_id()}")
        return

    streams = resolve_byprop("type", args.type, timeout=args.timeout)
    if not streams:
        print(f"[WARN] Aucun flux type='{args.type}' (timeout {args.timeout}s).")
        alls = resolve_streams(1.0)
        if alls:
            print("[INFO] Flux existants:")
            for s in alls:
                print(f"   name={s.name()} type={s.type()} ch={s.channel_count()} fs={s.nominal_srate()}")
        return

    info = streams[0]
    print(f"[OK] name={info.name()} type={info.type()} ch={info.channel_count()} fs={info.nominal_srate()} id={info.source_id()}")
    labs = channel_labels(info)
    if labs:
        print(f"[OK] ch_names: {labs}")

    inlet = StreamInlet(info, max_buflen=10, max_chunklen=args.max_samples)
    for i in range(args.n):
        samples, ts = inlet.pull_chunk(timeout=2.0, max_samples=args.max_samples)
        if not samples:
            print(f"[{i+1}/{args.n}] chunk vide")
            continue
        arr = np.asarray(samples, dtype=np.float32)
        mn, mx = float(np.nanmin(arr)), float(np.nanmax(arr))
        print(f"[{i+1}/{args.n}] shape={arr.shape} min={mn:.3g} max={mx:.3g}")
    print("[DONE]")

if __name__ == "__main__":
    main()
