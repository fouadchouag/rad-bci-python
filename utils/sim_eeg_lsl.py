# utils/sim_eeg_lsl.py
# Simulateur LSL d'EEG : 8 canaux @ 250 Hz, amplitude réaliste (~50 µV crête-à-crête).
# Sortie en Volts (comme les vrais amplis). Compatible Windows/PowerShell.
# Dépendances : pip install pylsl numpy

import time
import math
import numpy as np
from pylsl import StreamInfo, StreamOutlet

# ------------------- Paramètres du flux -------------------
FS = 250            # fréquence d'échantillonnage (Hz)
N_CH = 8            # nombre de canaux
CHUNK = 50          # nb d'échantillons envoyés par paquet
SCALE = 50e-6       # ~50 µV crête-à-crête (en Volts)
NAME = "SimEEG"     # nom du flux LSL
UID = "simeeg-001"  # identifiant source (unique si plusieurs émetteurs)

# ------------------- Déclaration du stream ----------------
info = StreamInfo(NAME, 'EEG', N_CH, FS, 'float32', UID)

# Métadonnées de canaux (labels & unités)
chns = info.desc().append_child("channels")
for i in range(N_CH):
    ch = chns.append_child("channel")
    ch.append_child_value("label", f"Ch{i+1}")
    ch.append_child_value("unit", "V")
    ch.append_child_value("type", "EEG")

outlet = StreamOutlet(info, chunk_size=CHUNK, max_buffered=360)

print(f"[SimEEG] Streaming {N_CH} channels @ {FS} Hz, chunk={CHUNK} (Ctrl+C pour arrêter)")

# ------------------- Génération du signal -----------------
t = 0
phase = np.linspace(0.0, math.pi, N_CH)  # phase différente par canal

try:
    while True:
        # temps pour ce chunk
        tt = (t + np.arange(CHUNK)) / FS  # shape (CHUNK,)

        # Composantes EEG synthétiques
        alpha = np.sin(2*np.pi*10*tt)           # 10 Hz
        beta  = 0.2*np.sin(2*np.pi*20*tt)       # 20 Hz (faible)
        drift = 0.05*np.sin(2*np.pi*0.2*tt)     # dérive lente
        base  = alpha + beta + drift            # (CHUNK,)

        # Applique une phase par canal + bruit blanc
        buf = base[:, None] * np.cos(phase)[None, :]                # (CHUNK, N_CH)
        buf += 0.3 * np.random.randn(CHUNK, N_CH)                   # bruit
        buf = (buf * SCALE).astype(np.float32, order='C')           # -> Volts, C-contigu

        # Envoi LSL (format attendu: (n_samples, n_channels))
        try:
            outlet.push_chunk(buf)
        except Exception:
            # Fallback ultra-sûr si jamais une lib casse sur ndarray
            outlet.push_chunk(buf.tolist())

        t += CHUNK
        time.sleep(CHUNK / FS)

except KeyboardInterrupt:
    print("\n[SimEEG] Arrêt demandé par l'utilisateur. Bye.")
