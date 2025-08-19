#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LSL Emulator (EEG + Markers [+ GroundTruth opt]) for BCI pipelines
Scenarios: MI, P300, SSVEP

Exemples :
  python utils/lsl_emulator.py --scenario MI --duration 180 --srate 250 --marker-lag-ms 10 --jitter-ms 2 --gt
  python utils/lsl_emulator.py --scenario P300 --srate 250 --duration 120 --p300-target-prob 0.25 --gt
  python utils/lsl_emulator.py --scenario SSVEP --freqs 10,12,15 --duration 90 --jitter-ms 4 --control-stdin

Pendant l'exécution avec --control-stdin, vous pouvez taper :
  MI NEXT 769
  MI ORDER 770,769,771,772
  SSVEP NEXT 12
  SSVEP FREQS 10,12,15
  P300 PROB 0.3
  STATUS
  STOP
"""

import argparse, time, sys, threading, math, os
import numpy as np

# Réduit des warnings multicast IPv6 sous Windows
os.environ.setdefault("LSL_NO_IPV6", "1")

try:
    from pylsl import StreamInfo, StreamOutlet, local_clock
except Exception as e:
    print("pylsl non installé. Fais:  pip install pylsl")
    raise

# -------------------------- Définition de montage --------------------------
EEG_CH = [
    # 22 EEG proche Graz
    "Fz","Cz","Pz","Oz",
    "F3","F4","C3","C4","P3","P4","O1","O2",
    "F7","F8","T7","T8","P7","P8","FC1","FC2","CP1","CP2",
]
EOG_CH = ["HEOG","VEOG","EOGz"]  # 3 EOG

REG = {
    "motor_L": ["C3","FC1","CP1"],
    "motor_R": ["C4","FC2","CP2"],
    "midline": ["Cz","Pz","Fz"],
    "occip":   ["O1","Oz","O2","P7","P8","P3","P4"]
}

def idx_of(names, allnames):
    return [allnames.index(n) for n in names if n in allnames]

# -------------------------- Helpers signaux --------------------------
def band_limited_noise(low, high, samples, fs):
    """Bruit coloré bande [low,high] par fenêtrage fréquentiel (indépendant par chunk)."""
    if samples <= 0:
        return np.zeros((0,), np.float32)
    freqs = np.fft.rfftfreq(samples, d=1.0/fs)
    f = np.zeros(freqs.shape, dtype=np.complex128)
    band = (freqs >= low) & (freqs <= high)
    if not np.any(band):
        return np.random.randn(samples).astype(np.float32)
    phase = np.exp(1j * 2*np.pi * np.random.rand(np.count_nonzero(band)))
    amp = 1.0/np.maximum(1.0, freqs[band])
    f[band] = amp * phase
    x = np.fft.irfft(f, n=samples)
    x = x / (np.std(x) + 1e-9)
    return x.astype(np.float32)

def erp_template(fs, peak_ms=300, amp=4.0, width_ms=180):
    """Bossette P300 ~0..800ms avec petites composantes N1/P2."""
    t = np.arange(0, int(0.8*fs))
    mu = int(peak_ms * fs/1000.0)
    sig = max(1, int(width_ms * fs/1000.0))
    y = amp * np.exp(-0.5*((t-mu)/sig)**2)
    y -= 1.5 * np.exp(-0.5*((t - int(120*fs/1000.0))/max(1,int(25*fs/1000.0)))**2)
    y += 0.8 * np.exp(-0.5*((t - int(200*fs/1000.0))/max(1,int(30*fs/1000.0)))**2)
    return y.astype(np.float32)

def blink_wave(fs, dur_ms=150, amp=120.0):
    """Clignement EOG grossier."""
    n = max(1, int(dur_ms * fs/1000.0))
    t = np.linspace(-2.5, 2.5, n)
    y = amp * np.exp(-t**2)
    return y.astype(np.float32)

# -------------------------- Base de scénario --------------------------
class Scenario:
    def __init__(self, fs, ch_names, eog_names, args):
        self.fs = fs
        self.ch = ch_names if ch_names else EEG_CH[:]   # fallback
        self.eog_ch = eog_names if eog_names else EOG_CH[:]
        self.args = args
        self.t = 0.0  # temps "scénario" (s)

        self.i_motor_L = idx_of(REG["motor_L"], self.ch)
        self.i_motor_R = idx_of(REG["motor_R"], self.ch)
        self.i_midline = idx_of(REG["midline"], self.ch)
        self.i_occip   = idx_of(REG["occip"], self.ch)

        self.eog_last_blink_end = -9999.0
        self.eog_active = None  # (wave, idx, start_time)

        self._cmd = {}  # commandes runtime (next_trial, next_freq, etc.)

        if getattr(args, "seed", None) is not None:
            np.random.seed(args.seed)

    # Hooks runtime (utilisés par --control-stdin)
    def set_next_trial(self, code: int):
        self._cmd["next_trial"] = int(code)

    def set_next_freq(self, f: float):
        self._cmd["next_freq"] = float(f)

    def set_p300_prob(self, p: float):
        # seulement si le scénario P300 a cet attribut
        if hasattr(self, "target_prob"):
            self.target_prob = max(0.0, min(1.0, float(p)))

    def set_ssvep_freqs(self, freqs):
        if hasattr(self, "freqs"):
            self.freqs = [float(x) for x in freqs]

    def step(self, n_samp):
        """Retourne (eeg, eog, markers) pour n_samp échantillons.
           markers : liste de tuples (t_abs_scenario, code_str)."""
        raise NotImplementedError

    # ---- EOG synthé + fuite vers EEG frontal ----
    def synth_eog(self, n_samp):
        eog = np.zeros((n_samp, len(self.eog_ch)), dtype=np.float32)
        # blink aléatoire toutes 2–6 s
        if (self.t - self.eog_last_blink_end) > (2.0 + 4.0*np.random.rand()):
            w = blink_wave(self.fs, dur_ms=120 + int(80*np.random.rand()), amp=80+80*np.random.rand())
            self.eog_active = (w, 0, self.t)
            self.eog_last_blink_end = self.t + len(w)/self.fs
        if self.eog_active is not None:
            w, _, t0 = self.eog_active
            start = int((self.t - t0)*self.fs)
            if start < len(w):
                take = min(n_samp, len(w)-start)
                eog[:take, 1] += w[start:start+take]       # VEOG
                eog[:take, 0] += 0.5*w[start:start+take]   # HEOG
                eog[:take, 2] += 0.3*w[start:start+take]   # EOGz
            else:
                self.eog_active = None
        # drift lent
        eog += (np.cumsum(0.01*np.random.randn(n_samp,1), axis=0) * np.array([0.0,1.0,0.2])).astype(np.float32)
        return eog

    def leak_eog_into_eeg(self, eeg, eog):
        leak_idx = [self.ch.index(c) for c in ["Fz","F3","F4","F7","F8"] if c in self.ch]
        if not leak_idx: return eeg
        leak_gain = getattr(self.args, "eog_leak", 0.05)
        eeg[:, leak_idx] += float(leak_gain) * eog[:,1:2]  # VEOG -> frontal
        return eeg

# -------------------------- Scénario MI --------------------------
class ScenarioMI(Scenario):
    """4 classes: 769 L, 770 R, 771 Feet, 772 Tongue
       2s base, 4s imagerie, 2s repos."""
    def __init__(self, fs, ch_names, eog_names, args):
        super().__init__(fs, ch_names, eog_names, args)
        order = getattr(args, "mi_order", None)
        if order:
            try:
                self.trial_order = [int(x) for x in order.split(",")]
            except Exception:
                self.trial_order = [769,770,771,772]
        else:
            self.trial_order = [769,770,771,772]
        np.random.shuffle(self.trial_order)
        self.trial_len = float(getattr(args, "mi_trial_len", 8.0))
        self.cue_on = 2.0
        self.imag_on = 2.0
        self.imag_off = 6.0
        self.next_trial_t0 = 0.0
        self.curr_code = None

    def step(self, n_samp):
        dt = n_samp / self.fs
        t0 = self.t; t1 = self.t + dt

        eeg = np.zeros((n_samp, len(self.ch)), np.float32)
        for ci in range(eeg.shape[1]):
            eeg[:, ci] = band_limited_noise(1, 40, n_samp, self.fs)

        mu = 10.0 + np.random.randn()*0.2
        be = 20.0 + np.random.randn()*0.5
        tt = self.t + np.arange(n_samp)/self.fs
        mu_osc = 2.0*np.sin(2*np.pi*mu*tt)
        be_osc = 1.2*np.sin(2*np.pi*be*tt)
        eeg[:, self.i_motor_L] += (mu_osc[:,None] + 0.6*be_osc[:,None]).astype(np.float32)
        eeg[:, self.i_motor_R] += (mu_osc[:,None] + 0.6*be_osc[:,None]).astype(np.float32)
        eeg[:, self.i_midline] += 0.6*mu_osc[:,None]

        markers=[]

        # planifier les essais
        while self.next_trial_t0 <= t1:
            # support commande "NEXT"
            if self._cmd.get("next_trial") in (769,770,771,772):
                code = int(self._cmd.pop("next_trial"))
            else:
                code = self.trial_order[0]
                self.trial_order = self.trial_order[1:] + [code]
            self.curr_code = code
            cue_ts = self.next_trial_t0 + self.cue_on
            lag = (self.args.marker_lag_ms or 0)/1000.0
            jitter = (np.random.randn()*(self.args.jitter_ms or 0)/1000.0)
            markers.append((cue_ts + lag + jitter, str(code)))
            self.next_trial_t0 += self.trial_len

        # ERD/ERS pendant imagerie
        for k in range(-2, 1):
            t0_trial = self.next_trial_t0 + k*self.trial_len
            if t0_trial < t1 and (t0_trial + self.trial_len) > t0:
                code = self.trial_order[k-1] if k<0 else self.curr_code
                i0 = max(0, int(max(0.0, (t0_trial + self.imag_on) - t0) * self.fs))
                i1 = min(n_samp, int(max(0.0, (t0_trial + self.imag_off) - t0) * self.fs))
                if i1 > i0:
                    if code == 769:   # main gauche -> ERD sur motor_R
                        eeg[i0:i1, :][:, self.i_motor_R] *= 0.55
                    elif code == 770: # main droite -> ERD sur motor_L
                        eeg[i0:i1, :][:, self.i_motor_L] *= 0.55
                    elif code == 771: # pieds -> midline
                        eeg[i0:i1, :][:, self.i_midline] *= 0.6
                    elif code == 772: # langue -> bilatéral léger
                        eeg[i0:i1, :][:, self.i_motor_L] *= 0.8
                        eeg[i0:i1, :][:, self.i_motor_R] *= 0.8

        eog = self.synth_eog(n_samp)
        eeg = self.leak_eog_into_eeg(eeg, eog)

        self.t += dt
        return eeg, eog, markers

# -------------------------- Scénario P300 --------------------------
class ScenarioP300(Scenario):
    """Oddball ~3.3 Hz, 20% cibles. ERP sur Pz/Cz/Oz.
       Marqueurs: TGT / NT."""
    def __init__(self, fs, ch_names, eog_names, args):
        super().__init__(fs, ch_names, eog_names, args)
        self.stim_rate = float(getattr(args, "p300_rate", 3.33))
        self.next_stim_t = 0.5
        self.target_prob = float(getattr(args, "p300_target_prob", 0.2))
        self.erp = erp_template(fs, peak_ms=300, amp=5.0, width_ms=180)
        self.erp_buffers = []   # (start_t, idx_list, polarity, is_target)
        self.i_p300 = idx_of(["Pz","Cz","Oz","P3","P4","O1","O2"], self.ch)

    def step(self, n_samp):
        dt = n_samp / self.fs
        t0 = self.t; t1 = self.t + dt

        eeg = np.zeros((n_samp, len(self.ch)), np.float32)
        for ci in range(eeg.shape[1]):
            eeg[:, ci] = band_limited_noise(1, 40, n_samp, self.fs)

        markers=[]

        # stimuli
        while self.next_stim_t <= t1:
            is_t = (np.random.rand() < self.target_prob)
            code = "TGT" if is_t else "NT"
            lag = (self.args.marker_lag_ms or 0)/1000.0
            jitter = (np.random.randn()*(self.args.jitter_ms or 0)/1000.0)
            markers.append((self.next_stim_t + lag + jitter, code))
            self.erp_buffers.append((self.next_stim_t, self.i_p300, 1.0 if is_t else 0.2, is_t))
            self.next_stim_t += 1.0/self.stim_rate

        # ERP ajoutées
        for (t_start, idxs, pol, is_t) in list(self.erp_buffers):
            rel0 = int((t0 - t_start)*self.fs)
            rel1 = int((t1 - t_start)*self.fs)
            a0 = max(0, rel0)
            a1 = min(len(self.erp), rel1)
            if a1 > a0:
                s0 = a0 - rel0
                s1 = s0 + (a1 - a0)
                eeg[s0:s1, :][:, idxs] += (pol*self.erp[a0:a1, None]).astype(np.float32)
            if rel1 >= len(self.erp):
                self.erp_buffers.remove((t_start, idxs, pol, is_t))

        eog = self.synth_eog(n_samp)
        eeg = self.leak_eog_into_eeg(eeg, eog)

        self.t += dt
        return eeg, eog, markers

# -------------------------- Scénario SSVEP --------------------------
class ScenarioSSVEP(Scenario):
    """Blocs: rest + focus; fréquences par défaut 10/12/15 Hz.
       Marqueur: FREQ_<f> au début du focus."""
    def __init__(self, fs, ch_names, eog_names, args):
        super().__init__(fs, ch_names, eog_names, args)
        if getattr(args, "freqs", ""):
            self.freqs = [float(x) for x in args.freqs.split(",")]
        else:
            self.freqs = [10.0, 12.0, 15.0]
        self.block_len = float(getattr(args, "block_len", 8.0))
        self.rest = float(getattr(args, "rest", 3.0))
        self.focus = float(getattr(args, "focus", 5.0))
        self.next_block_t0 = 0.0
        self.curr_f = None

    def step(self, n_samp):
        dt = n_samp / self.fs
        t0 = self.t; t1 = self.t + dt

        eeg = np.zeros((n_samp, len(self.ch)), np.float32)
        for ci in range(eeg.shape[1]):
            eeg[:, ci] = band_limited_noise(1, 40, n_samp, self.fs)

        markers=[]

        while self.next_block_t0 <= t1:
            # support commande "NEXT"
            if "next_freq" in self._cmd:
                self.curr_f = float(self._cmd.pop("next_freq"))
            else:
                self.curr_f = float(np.random.choice(self.freqs))
            lag = (self.args.marker_lag_ms or 0)/1000.0
            jitter = (np.random.randn()*(self.args.jitter_ms or 0)/1000.0)
            markers.append((self.next_block_t0 + self.rest + lag + jitter, f"FREQ_{self.curr_f:.2f}"))
            self.next_block_t0 += self.block_len

        # ajout SSVEP sur occipital pendant focus
        i0 = max(0, int(max(0.0, (self.next_block_t0 - self.block_len + self.rest) - t0)*self.fs))
        i1 = min(n_samp, int(max(0.0, (self.next_block_t0 - self.block_len + self.rest + self.focus) - t0)*self.fs))
        if (self.curr_f is not None) and (i1 > i0):
            t = (np.arange(i0, i1)/self.fs + (t0))
            sig = 5.0*np.sin(2*np.pi*self.curr_f*t) + 2.5*np.sin(2*np.pi*2*self.curr_f*t)
            eeg[i0:i1, :][:, self.i_occip] += sig[:,None].astype(np.float32)

        eog = self.synth_eog(n_samp)
        eeg = self.leak_eog_into_eeg(eeg, eog)

        self.t += dt
        return eeg, eog, markers

# -------------------------- Serveur LSL --------------------------
class LSLEmulator:
    def __init__(self, scenario, fs, eeg_channels, eog_channels, name_prefix, gt):
        self.scenario = scenario
        self.fs = fs
        self.ch_eeg = eeg_channels if eeg_channels else EEG_CH[:]
        self.ch_eog = eog_channels if eog_channels else EOG_CH[:]
        self.name_prefix = name_prefix
        self.include_gt = gt

        # EEG outlet
        info = StreamInfo(name=f"{name_prefix}_EEG", type='EEG',
                          channel_count=len(self.ch_eeg), nominal_srate=fs,
                          channel_format='float32', source_id=f"{name_prefix}_EEG_src")
        chn = info.desc().append_child("channels")
        for c in self.ch_eeg:
            chn.append_child("channel").append_child_value("label", c).append_child_value("unit","uV").append_child_value("type","EEG")
        info.desc().append_child_value("manufacturer","SimBCI").append_child_value("simulated","true")
        self.out_eeg = StreamOutlet(info, chunk_size=0, max_buffered=360)

        # EOG outlet
        info_eog = StreamInfo(name=f"{name_prefix}_EOG", type='EOG',
                              channel_count=len(self.ch_eog), nominal_srate=fs,
                              channel_format='float32', source_id=f"{name_prefix}_EOG_src")
        chn2 = info_eog.desc().append_child("channels")
        for c in self.ch_eog:
            chn2.append_child("channel").append_child_value("label", c).append_child_value("unit","uV").append_child_value("type","EOG")
        self.out_eog = StreamOutlet(info_eog, chunk_size=0, max_buffered=360)

        # Markers outlet
        info_m = StreamInfo(name=f"{name_prefix}_Markers", type='Markers',
                            channel_count=1, nominal_srate=0, channel_format='string',
                            source_id=f"{name_prefix}_Markers_src")
        self.out_mark = StreamOutlet(info_m)

        # Ground truth per-sample (optionnel)
        self.out_gt = None
        if self.include_gt:
            info_gt = StreamInfo(name=f"{name_prefix}_GT", type='GT',
                                 channel_count=1, nominal_srate=fs, channel_format='int32',
                                 source_id=f"{name_prefix}_GT_src")
            self.out_gt = StreamOutlet(info_gt, chunk_size=0, max_buffered=360)

        self._stop = False
        self._start_wall = None  # base de temps LSL pour horodater les marqueurs

    def run(self, duration_s, chunk_ms=20):
        print(f"[LSL] Start for {duration_s}s | fs={self.fs} | chunk={chunk_ms} ms")
        dt = chunk_ms/1000.0
        ns = int(round(self.fs*dt))
        self._start_wall = local_clock()           # base de temps LSL
        end_time = self._start_wall + duration_s
        gt_last = 0

        while (not self._stop) and (local_clock() < end_time):
            loop_start = local_clock()

            # Génère un chunk
            eeg, eog, markers = self.scenario.step(ns)

            # Timestamp du 1er échantillon (compat pylsl anciennes et nouvelles)
            ts0 = local_clock()

            # pylsl récents: timestamps vectoriels ; sinon: timestamp unique
            try:
                ts_vec = [ts0 + i/self.fs for i in range(ns)]
                self.out_eeg.push_chunk(eeg.tolist(), timestamps=ts_vec)
                self.out_eog.push_chunk(eog.tolist(), timestamps=ts_vec)
                if self.out_gt is not None:
                    gt_chunk = [gt_last] * ns
                    self.out_gt.push_chunk([[int(v)] for v in gt_chunk], timestamps=ts_vec)
            except TypeError:
                self.out_eeg.push_chunk(eeg.tolist(), timestamp=ts0)
                self.out_eog.push_chunk(eog.tolist(), timestamp=ts0)
                if self.out_gt is not None:
                    gt_chunk = [gt_last] * ns
                    self.out_gt.push_chunk([[int(v)] for v in gt_chunk], timestamp=ts0)

            # Pousser les marqueurs à t_abs = base + t_scenario
            for (t_rel, code) in markers:
                t_abs = self._start_wall + float(t_rel)
                self.out_mark.push_sample([str(code)], timestamp=t_abs)

            # Mettre à jour GT "dernier code"
            if markers:
                last = markers[-1][1]
                if last.isdigit():                # MI 769..772
                    gt_last = int(last) - 768     # 1..4
                elif last.startswith("FREQ_"):    # SSVEP
                    try:
                        gt_last = int(100*float(last.split("_")[1]))
                    except Exception:
                        gt_last = 0
                elif last in ("TGT","NT"):        # P300
                    gt_last = 1 if last=="TGT" else 0

            # pacing
            sleep_left = dt - (local_clock() - loop_start)
            if sleep_left > 0:
                time.sleep(sleep_left)

        print("[LSL] Stop.")

    def stop(self):
        self._stop = True

# -------------------------- Contrôle par stdin (optionnel) --------------------------
def control_stdin_loop(server: LSLEmulator):
    """
    Lit des commandes sur stdin pendant que le serveur tourne.
    Commandes:
      MI NEXT <769|770|771|772>
      MI ORDER <csv>
      SSVEP NEXT <freq>
      SSVEP FREQS <csv>
      P300 PROB <0..1>
      STATUS
      STOP
    """
    print("[CTRL] Tapez des commandes (ex: 'MI NEXT 769', 'SSVEP NEXT 12', 'P300 PROB 0.3', 'STOP'):")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = line.strip()
        if not cmd:
            continue
        parts = cmd.split()
        try:
            if parts[0].upper() == "STOP":
                print("[CTRL] STOP reçu.")
                server.stop()
                break

            elif parts[0].upper() == "STATUS":
                print(f"[CTRL] status fs={server.fs} running")

            elif parts[0].upper() == "MI":
                if len(parts) >= 3 and parts[1].upper() == "NEXT":
                    code = int(parts[2])
                    if hasattr(server.scenario, "set_next_trial"):
                        server.scenario.set_next_trial(code)
                        print(f"[CTRL] MI next trial = {code}")
                elif len(parts) >= 3 and parts[1].upper() == "ORDER":
                    csv = parts[2] if len(parts)==3 else parts[2:]
                    if isinstance(csv, list):
                        csv = " ".join(csv)
                    try:
                        order = [int(x.strip().strip(',')) for x in csv.split(",")]
                        if hasattr(server.scenario, "trial_order"):
                            server.scenario.trial_order = order[:]
                            print(f"[CTRL] MI order = {order}")
                    except Exception as e:
                        print(f"[CTRL] MI ORDER invalide: {e}")

            elif parts[0].upper() == "SSVEP":
                if len(parts) >= 3 and parts[1].upper() == "NEXT":
                    f = float(parts[2])
                    if hasattr(server.scenario, "set_next_freq"):
                        server.scenario.set_next_freq(f)
                        print(f"[CTRL] SSVEP next freq = {f}")
                elif len(parts) >= 3 and parts[1].upper() == "FREQS":
                    csv = parts[2] if len(parts)==3 else " ".join(parts[2:])
                    try:
                        freqs = [float(x.strip().strip(',')) for x in csv.split(",")]
                        if hasattr(server.scenario, "set_ssvep_freqs"):
                            server.scenario.set_ssvep_freqs(freqs)
                            print(f"[CTRL] SSVEP freqs = {freqs}")
                    except Exception as e:
                        print(f"[CTRL] SSVEP FREQS invalide: {e}")

            elif parts[0].upper() == "P300":
                if len(parts) >= 3 and parts[1].upper() == "PROB":
                    p = float(parts[2])
                    if hasattr(server.scenario, "set_p300_prob"):
                        server.scenario.set_p300_prob(p)
                        print(f"[CTRL] P300 target prob = {p}")

            else:
                print(f"[CTRL] Commande inconnue: {cmd}")

        except Exception as e:
            print(f"[CTRL] Erreur commande '{cmd}': {e}")

# -------------------------- Main --------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["MI","P300","SSVEP"], default="MI")
    ap.add_argument("--srate", type=float, default=250.0)
    ap.add_argument("--duration", type=float, default=120.0, help="seconds")
    ap.add_argument("--name", type=str, default="SimBCI")
    ap.add_argument("--gt", action="store_true", help="emit per-sample GroundTruth stream")
    ap.add_argument("--marker-lag-ms", type=float, default=0.0, help="constant output lag on markers")
    ap.add_argument("--jitter-ms", type=float, default=0.0, help="gaussian jitter on marker times (std)")
    ap.add_argument("--freqs", type=str, default="", help="SSVEP freqs comma sep, e.g. 8.57,10,12")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--chunk-ms", type=int, default=20)

    # Options avancées
    ap.add_argument("--eog-leak", type=float, default=0.05, help="gain de fuite EOG vers EEG frontal")
    # MI
    ap.add_argument("--mi-order", type=str, default="", help="ordre des codes MI, ex: 769,770,771,772")
    ap.add_argument("--mi-trial-len", type=float, default=8.0)
    # P300
    ap.add_argument("--p300-rate", type=float, default=3.33)
    ap.add_argument("--p300-target-prob", type=float, default=0.2)
    # SSVEP block design
    ap.add_argument("--block-len", type=float, default=8.0)
    ap.add_argument("--rest", type=float, default=3.0)
    ap.add_argument("--focus", type=float, default=5.0)

    # Contrôle interactif
    ap.add_argument("--control-stdin", action="store_true", help="activer la lecture de commandes sur stdin")

    args = ap.parse_args()

    fs = float(args.srate)
    ch_names = EEG_CH[:]
    eog_names = EOG_CH[:]

    if args.scenario == "MI":
        scen = ScenarioMI(fs, ch_names, eog_names, args)
    elif args.scenario == "P300":
        scen = ScenarioP300(fs, ch_names, eog_names, args)
    else:
        scen = ScenarioSSVEP(fs, ch_names, eog_names, args)

    server = LSLEmulator(scen, fs, ch_names, eog_names, args.name, args.gt)

    ctrl_thread = None
    if args.control_stdin:
        ctrl_thread = threading.Thread(target=control_stdin_loop, args=(server,), daemon=True)
        ctrl_thread.start()

    try:
        server.run(duration_s=float(args.duration), chunk_ms=int(args.chunk_ms))
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        if ctrl_thread is not None:
            try:
                ctrl_thread.join(timeout=0.5)
            except Exception:
                pass

if __name__ == "__main__":
    main()
