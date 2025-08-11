# external_scripts/bandpower_ext.py

import os, json, argparse
import numpy as np

def bandpower_welch_like(x, sfreq, bands):
    """
    Estimation simple de la puissance par bande, sans SciPy:
    - fenêtrage Hann
    - FFT réelle (rfft)
    - PSD ~ |X|^2 / N
    - somme/ moyenne des bins dans chaque bande
    """
    x = np.asarray(x, dtype=float)
    n = x.shape[-1]
    if n <= 1 or sfreq <= 0:
        return {k: float("nan") for k in bands.keys()}

    # Hann window
    w = np.hanning(n)
    xw = x * w

    # rFFT
    X = np.fft.rfft(xw, n=n)
    psd = (np.abs(X) ** 2) / n  # PSD approximative
    freqs = np.fft.rfftfreq(n, d=1.0 / sfreq)

    # Puissance moyenne dans chaque bande
    out = {}
    for bname, (fmin, fmax) in bands.items():
        idx = np.where((freqs >= fmin) & (freqs < fmax))[0]
        if idx.size == 0:
            out[bname] = float("nan")
        else:
            out[bname] = float(np.mean(psd[idx]))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # Charge l'input
    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    segment = np.asarray(payload["segment"], dtype=float)  # (n_ch, n_samples)
    sfreq = float(payload["sfreq"])
    ch_names = list(payload["ch_names"])
    bands = payload.get("bands", {
        "delta": [1.0, 4.0],
        "theta": [4.0, 8.0],
        "alpha": [8.0, 13.0],
        "beta":  [13.0, 30.0],
        "gamma": [30.0, 45.0],
    })

    n_ch = segment.shape[0]
    features = {}
    for i in range(n_ch):
        bp = bandpower_welch_like(segment[i], sfreq, bands)
        features[ch_names[i] if i < len(ch_names) else f"ch{i}"] = bp

    out = {
        "features": features,
        "band_labels": list(bands.keys())
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f)

    print(f"[bandpower_ext] OK: {n_ch} ch, fs={sfreq:.2f}, out={args.output}")


if __name__ == "__main__":
    main()
