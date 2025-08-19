# utils/lsl_chunk_emulator.py
# -*- coding: utf-8 -*-
import argparse, math, time, sys
import numpy as np
from pylsl import StreamInfo, StreamOutlet, local_clock

def parse_pattern(s):
    """
    "3L,5R,2L,1R" -> [('L',3),('R',5),('L',2),('R',1)]
    """
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok: continue
        n = ""
        cls = ""
        for ch in tok:
            if ch.isdigit(): n += ch
            else: cls += ch
        if not n: continue
        n = int(n)
        cls = cls.strip().upper()
        if cls not in ("L","R","0","1"):
            raise ValueError(f"Bad class token '{tok}' (use L/R or 0/1).")
        # normalise en L/R
        if cls == "0": cls = "L"
        if cls == "1": cls = "R"
        out.append((cls, n))
    if not out:
        raise ValueError("Empty pattern.")
    return out

def idx_of(ch_names, name):
    name = name.upper()
    for i, ch in enumerate(ch_names):
        if name == str(ch).upper():
            return i
    return None

def synth_chunk(t0, ns, fs, label, ch_names, phases):
    """
    Retourne (ns, C) float32
    label: 'L' ou 'R'
    phases: dict canal -> (pha_alpha, pha_beta), mis à jour pour continuité de phase
    """
    C = len(ch_names)
    t = t0 + np.arange(ns)/fs

    # composants oscillatoires
    f_alpha = 10.0
    f_beta  = 20.0
    amp_alpha = 8.0   # µV ~ relatif (arbitraire)
    amp_beta  = 5.0

    # indices de canaux clés (si présents)
    iC3 = idx_of(ch_names, "C3")
    iC4 = idx_of(ch_names, "C4")

    # facteurs ERD par classe (diminution d’amplitude alpha/beta)
    k_alpha = np.ones(C)
    k_beta  = np.ones(C)
    if label == "L" and iC4 is not None:
        k_alpha[iC4] = 0.5
        k_beta[iC4]  = 0.5
    if label == "R" and iC3 is not None:
        k_alpha[iC3] = 0.5
        k_beta[iC3]  = 0.5

    # bruit de fond
    noise = 1.5 * np.random.randn(ns, C).astype(np.float32)

    # oscillateurs alpha/beta continus
    out = noise.copy()
    for c in range(C):
        pha_a, pha_b = phases.get(c, (2*np.pi*np.random.rand(), 2*np.pi*np.random.rand()))
        # sinusoïdes
        sig_a = (amp_alpha * k_alpha[c]) * np.sin(2*np.pi*f_alpha*t + pha_a)
        sig_b = (amp_beta  * k_beta[c])  * np.sin(2*np.pi*f_beta *t + pha_b)
        out[:, c] += sig_a.astype(np.float32) + sig_b.astype(np.float32)
        # maj phases pour continuité
        pha_a = (pha_a + 2*np.pi*f_alpha*ns/fs) % (2*np.pi)
        pha_b = (pha_b + 2*np.pi*f_beta *ns/fs) % (2*np.pi)
        phases[c] = (pha_a, pha_b)

    # un chouïa de drift lent sur Fp/Z si présents (style EOG/leak)
    for tag in ("FP1","FP2","FZ","CZ"):
        i = idx_of(ch_names, tag)
        if i is not None:
            out[:, i] += 0.1 * np.cumsum(0.01*np.random.randn(ns)).astype(np.float32)

    return out

def main():
    ap = argparse.ArgumentParser(description="LSL MI chunk-pattern emulator")
    ap.add_argument("--name", default="EEG_SIM_PATTERN", help="EEG stream name")
    ap.add_argument("--marker-name", default="Markers", help="Markers stream name")
    ap.add_argument("--srate", type=float, default=250.0)
    ap.add_argument("--chunk-ms", type=int, default=20, help="chunk size in ms")
    ap.add_argument("--duration", type=float, default=120.0, help="seconds (<=0 for infinite)")
    ap.add_argument("--channels", default="C3,Cz,C4,Pz,Oz,F3,Fz,F4",
                    help="comma-separated channel names")
    ap.add_argument("--pattern", default="3L,5R,2L,1R", help="e.g. 3L,5R,2L,1R")
    ap.add_argument("--numeric-markers", action="store_true", help="emit 0/1 instead of L/R")
    ap.add_argument("--marker-every-chunk", action="store_true",
                    help="if set, push a marker for each chunk; else only at chunk #1 of each block")
    args = ap.parse_args()

    ch_names = [c.strip() for c in args.channels.split(",") if c.strip()]
    C = len(ch_names)
    fs = float(args.srate)
    ns = max(1, int(round(fs * (args.chunk_ms/1000.0))))

    # LSL EEG stream
    info = StreamInfo(args.name, 'EEG', C, fs, 'float32', f"{args.name}_src")
    # (Optionnel: desc/chans)
    chns = info.desc().append_child("channels")
    for nm in ch_names:
        ch = chns.append_child("channel")
        ch.append_child_value("label", nm)
        ch.append_child_value("unit", "uV")
        ch.append_child_value("type", "EEG")

    outlet_eeg = StreamOutlet(info, chunk_size=ns, max_buffered=360)

    # LSL Markers
    minfo = StreamInfo(args.marker_name, 'Markers', 1, 0, 'string', f"{args.marker_name}_src")
    outlet_mk = StreamOutlet(minfo)

    # pattern
    pat = parse_pattern(args.pattern)  # list of ('L'/'R', run_chunks)
    block_i = 0         # index dans le pattern
    chunk_in_block = 0  # position dans le run courant

    print(f"[LSL] Start | fs={fs} Hz | chunk={args.chunk_ms} ms ({ns} samples) | C={C}")
    print(f"[LSL] Pattern (loop): {pat}")
    t0 = local_clock()
    gsample = 0  # compteur d’échantillons pour la phase
    phases = {}  # phase alpha/beta par canal

    t_end = (t0 + args.duration) if args.duration > 0 else float("inf")

    try:
        while local_clock() < t_end:
            cls, run_len = pat[block_i]
            # push marker (début de bloc) :
            if chunk_in_block == 0 or args.marker_every_chunk:
                marker = cls if not args.numeric_markers else ("0" if cls == "L" else "1")
                outlet_mk.push_sample([marker])

            # synthèse du chunk
            chunk = synth_chunk(gsample/fs, ns, fs, cls, ch_names, phases)  # (ns, C)
            outlet_eeg.push_chunk(chunk.tolist())  # timestamps gérés par LSL

            # avance
            gsample += ns
            chunk_in_block += 1
            if chunk_in_block >= run_len:
                chunk_in_block = 0
                block_i = (block_i + 1) % len(pat)

            # tempo (approx)
            time.sleep(max(0.0, args.chunk_ms/1000.0 * 0.8))  # petit 0.8 pour compenser l’overhead
    except KeyboardInterrupt:
        print("\n[LSL] Interrupted by user.")
    finally:
        print("[LSL] Done.")

if __name__ == "__main__":
    main()
