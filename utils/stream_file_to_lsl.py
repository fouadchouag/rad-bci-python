# utils/stream_file_to_lsl.py
# -*- coding: utf-8 -*-
import argparse
import time
import os
import numpy as np

try:
    import mne
except Exception as e:
    raise SystemExit(f"[ERROR] mne requis pour lire EDF: {e}\n> pip install mne")

try:
    from pylsl import StreamInfo, StreamOutlet
except Exception as e:
    raise SystemExit(f"[ERROR] pylsl requis: {e}\n> pip install pylsl")

def add_labels(info, ch_names, kind="EEG"):
    desc = info.desc().append_child("channels")
    for nm in ch_names:
        ch = desc.append_child("channel")
        ch.append_child_value("label", nm)
        ch.append_child_value("type", kind)
        ch.append_child_value("unit", "uV")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="EDF/BDF/FIF, etc.")
    p.add_argument("--name", default="SimEEG", help="Nom du flux LSL")
    p.add_argument("--uid", default="simeeg-001", help="source_id LSL")
    p.add_argument("--chunk", type=int, default=50, help="échantillons par chunk")
    p.add_argument("--speed", type=float, default=1.0, help="vitesse de relecture (1.0 = temps réel)")
    p.add_argument("--loop", action="store_true", help="boucler à la fin")
    p.add_argument("--pick-eeg-only", "--eeg-only", dest="pick_eeg_only",
                   action="store_true", help="ne streamer que les canaux EEG")
    args = p.parse_args()

    if not os.path.exists(args.file):
        raise SystemExit(f"[ERROR] Fichier introuvable: {args.file}")

    print(f"[stream_file_to_lsl] Streaming {args.file}")
    raw = mne.io.read_raw(args.file, preload=True, verbose=False)

    if args.pick_eeg_only:
        try:
            picks = mne.pick_types(raw.info, eeg=True, meg=False, stim=False, eog=False, misc=False)
            raw.pick(picks)
        except Exception:
            # fallback: filtrer par type textuel
            ch_types = raw.get_channel_types()
            keep = [i for i,t in enumerate(ch_types) if t.lower() == "eeg"]
            raw.pick(keep)

    ch_names = list(raw.ch_names)
    fs = float(raw.info["sfreq"])
    n_ch = len(ch_names)
    if n_ch == 0 or fs <= 0:
        raise SystemExit("[ERROR] Signal invalide (pas de canaux ou fs<=0).")

    info = StreamInfo(name=args.name, type="EEG", channel_count=n_ch,
                      nominal_srate=fs, channel_format="float32", source_id=args.uid)
    add_labels(info, ch_names, "EEG")
    outlet = StreamOutlet(info, chunk_size=args.chunk, max_buffered=60)

    print(f"  -> {args.name} [{args.uid}] • {n_ch} ch @ {fs:.1f} Hz • chunk={args.chunk} • speed={args.speed}x"
          + (" • loop" if args.loop else ""))

    i0 = 0
    n_times = raw.n_times
    samples_per_chunk = max(1, int(args.chunk))
    # durée réelle d’un chunk dans le fichier
    base_dt = samples_per_chunk / fs

    try:
        while True:
            i1 = min(i0 + samples_per_chunk, n_times)
            if i1 <= i0:  # fin
                if args.loop:
                    i0 = 0
                    continue
                else:
                    break

            # MNE -> (n_ch, n_s)
            data, _ = raw[:, i0:i1]
            # (n_s, n_ch) contigu float32
            chunk = np.ascontiguousarray(data.T, dtype=np.float32)
            # push (toutes versions pylsl OK)
            outlet.push_chunk(chunk)

            # temporisation (speed)
            sleep_t = base_dt / max(1e-9, float(args.speed))
            if sleep_t > 0:
                time.sleep(sleep_t)

            i0 = i1
    except KeyboardInterrupt:
        pass

    print("[DONE]")

if __name__ == "__main__":
    main()
