#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone LSL EEG generator (no GUI).

Usage (terminal):
  python lsl_eeg_generator.py --name SimEEG --montage standard_1020 --channels 32 --sfreq 250

This publishes an EEG LSL outlet your existing LSL inlet can read.
If MNE is available, channel names will be taken from the chosen montage; else
it falls back to generic names Ch1..ChN.
"""
import argparse
import time
import numpy as np

try:
    from pylsl import StreamInfo, StreamOutlet
except Exception as e:
    raise SystemExit("pylsl is required. Install with: pip install pylsl")

# optional MNE for nice channel names
try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='SimEEG', help='LSL stream name')
    ap.add_argument('--montage', default='standard_1020',
                    choices=['standard_1020','standard_1005','biosemi64','easycap-M1','none'],
                    help='Channel naming source (only for names, not positions)')
    ap.add_argument('--channels', type=int, default=32, help='Number of EEG channels')
    ap.add_argument('--sfreq', type=float, default=250.0, help='Sampling rate (Hz)')
    ap.add_argument('--alpha', type=float, default=10.0, help='Alpha base frequency (Hz)')
    ap.add_argument('--amp', type=float, default=10e-6, help='Signal amplitude (Volts)')
    ap.add_argument('--noise', type=float, default=2e-6, help='Noise stdev (Volts)')
    ap.add_argument('--chunk', type=int, default=32, help='Samples per chunk')
    args = ap.parse_args()

    n_ch = int(args.channels)
    sf = float(args.sfreq)
    chunk = int(args.chunk)
    if n_ch <= 0 or sf <= 0 or chunk <= 0:
        raise SystemExit('Invalid channels/sfreq/chunk')

    # channel names
    if HAVE_MNE and args.montage != 'none':
        try:
            mont = mne.channels.make_standard_montage(args.montage)
            ch_names = mont.ch_names[:n_ch]
        except Exception:
            ch_names = [f'Ch{i+1}' for i in range(n_ch)]
    else:
        ch_names = [f'Ch{i+1}' for i in range(n_ch)]

    info = StreamInfo(name=args.name, type='EEG', channel_count=n_ch,
                      nominal_srate=sf, channel_format='float32', source_id='rbci-sim')
    outlet = StreamOutlet(info, chunk_size=chunk, max_buffered=360)

    print(f"Streaming LSL: name={args.name}, channels={n_ch}, sf={sf}Hz, chunk={chunk}")
    print("Channels:", ", ".join(ch_names))
    print("Press Ctrl+C to stop.")

    # signal model
    dt = 1.0 / sf
    t = 0.0
    freqs = np.linspace(args.alpha - 2.0, args.alpha + 2.0, n_ch)
    beta = np.linspace(18.0, 24.0, n_ch)
    amp = float(args.amp)
    noise = float(args.noise)

    try:
        while True:
            ts = t + np.arange(chunk) * dt
            sig = amp * (np.sin(2*np.pi*freqs[:, None]*ts) + 0.5*np.sin(2*np.pi*beta[:, None]*ts))
            sig += noise * np.random.randn(n_ch, chunk)
            outlet.push_chunk(sig.T.astype(np.float32).tolist())
            t += chunk * dt
            time.sleep(max(0.0, chunk * dt * 0.95))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == '__main__':
    main()
