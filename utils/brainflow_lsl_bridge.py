# tools/brainflow_lsl_bridge.py
# -*- coding: utf-8 -*-
"""
BrainFlow → LSL bridge
- Lit un board BrainFlow (ex: Synthetic) et publie un flux LSL type 'EEG'
- Conçu pour être robuste, testable et isolé (process séparé)

Dépendances:
    pip install brainflow pylsl numpy

Exemples:
    # 1) Carte synthétique (idéale pour tests)
    python tools/brainflow_lsl_bridge.py --board synthetic --lsl-name BF-Synth --chunk 50 --to-volts

    # 2) Cyton sur COM3 (exemple)
    python tools/brainflow_lsl_bridge.py --board cyton --serial COM3 --lsl-name BF-Cyton --chunk 50 --to-volts

Remarques:
- --to-volts convertit les µV de BrainFlow en Volts (conseillé pour aligner avec d'autres flux).
- Le script ajoute des labels de canaux et des métadonnées (board_id, units, etc.).
- Arrêt propre via Ctrl+C.
"""

import argparse
import signal
import sys
import time
import warnings
import uuid
from typing import Dict, Any, List
import numpy as np

# Filtrer le warning pkg_resources de BrainFlow
warnings.filterwarnings(
    "ignore", category=UserWarning, message=r"^pkg_resources is deprecated as an API"
)

try:
    from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
except Exception as e:
    print("[BF→LSL] ERREUR: brainflow non disponible. Installez: pip install brainflow")
    raise

try:
    from pylsl import StreamInfo, StreamOutlet, cf_float32
except Exception:
    print("[BF→LSL] ERREUR: pylsl non disponible. Installez: pip install pylsl")
    raise


def _board_id_from_string(s: str) -> int:
    """Map simple nom→BoardIds, ou accepte un entier."""
    s = (s or "").strip().lower()
    # Essai entier direct
    try:
        return int(s)
    except Exception:
        pass
    # Mapping minimal (ajoutez vos boards si besoin)
    known = {
        "synthetic": BoardIds.SYNTHETIC_BOARD.value,
        "cyton": BoardIds.CYTON_BOARD.value,
        "ganglion": BoardIds.GANGLION_BOARD.value,
        "galea": BoardIds.GALEA_BOARD.value,
        "muse2": BoardIds.MUSE_2_BOARD.value,
    }
    if s in known:
        return known[s]
    raise ValueError(f"Board inconnu: {s!r}. Donnez un id numérique ou un nom connu (synthetic, cyton, ganglion, galea, muse2).")


def _build_lsl_info(name: str, nch: int, sf: float, source_id: str, ch_names: List[str],
                    units: str, meta: Dict[str, Any]) -> StreamInfo:
    info = StreamInfo(name=name, type="EEG", channel_count=nch,
                      nominal_srate=sf, channel_format=cf_float32, source_id=source_id)
    desc = info.desc()
    desc.append_child_value("manufacturer", "BrainFlow")
    device = desc.append_child("device")
    for k, v in meta.items():
        device.append_child_value(str(k), str(v))

    chns = desc.append_child("channels")
    for lab in ch_names:
        ch = chns.append_child("channel")
        ch.append_child_value("label", lab)
        ch.append_child_value("unit", units)
        ch.append_child_value("type", "EEG")
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=str, default="synthetic", help="Nom ou id du board (ex: synthetic, cyton, 0, ...)")
    ap.add_argument("--serial", type=str, default="", help="Port série (ex: COM3 ou /dev/ttyUSB0) si applicable")
    ap.add_argument("--ip-address", type=str, default="", help="IP si applicable")
    ap.add_argument("--ip-port", type=int, default=0, help="Port IP si applicable")
    ap.add_argument("--ip-protocol", type=int, default=0, help="Protocole IP si applicable")
    ap.add_argument("--timeout", type=int, default=0, help="Timeout connexion si applicable (ms)")
    ap.add_argument("--other-info", type=str, default="", help="Infos supplémentaires si applicable")
    ap.add_argument("--mac-address", type=str, default="", help="MAC si applicable")
    ap.add_argument("--master-board", type=int, default=0, help="Master board (daisy)")
    ap.add_argument("--chunk", type=int, default=50, help="Taille chunks LSL (samples)")
    ap.add_argument("--lsl-name", type=str, default="", help="Nom LSL (défaut: BrainFlow-<board>)")
    ap.add_argument("--lsl-source-id", type=str, default="", help="Source ID LSL (défaut: bf-<board>-<uuid4>)")
    ap.add_argument("--to-volts", action="store_true", help="Convertir µV → V (recommandé)")
    args = ap.parse_args()

    try:
        BoardShim.enable_dev_board_logger()
    except Exception:
        pass

    board_id = _board_id_from_string(args.board)
    params = BrainFlowInputParams()
    params.serial_port = args.serial
    params.ip_address = args.ip_address
    params.ip_port = args.ip_port
    params.ip_protocol = args.ip_protocol
    params.timeout = args.timeout
    params.other_info = args.other_info
    params.mac_address = args.mac_address
    params.master_board = args.master_board

    print(f"[BF→LSL] Init board id={board_id} (board='{args.board}')")
    board = BoardShim(board_id, params)

    # Prépare session & start stream
    try:
        board.prepare_session()
        board.start_stream()
    except Exception as e:
        print(f"[BF→LSL] ERREUR init: {e}")
        try:
            board.release_session()
        except Exception:
            pass
        sys.exit(1)

    # Métadonnées BrainFlow
    try:
        sf = float(BoardShim.get_sampling_rate(board_id))
        eeg_rows = list(BoardShim.get_eeg_channels(board_id))
        nch = len(eeg_rows)
        if nch <= 0:
            raise RuntimeError("Aucun canal EEG.")
    except Exception as e:
        print(f"[BF→LSL] ERREUR méta board: {e}")
        try:
            board.stop_stream(); board.release_session()
        except Exception:
            pass
        sys.exit(1)

    ch_names = [f"BF{i+1}" for i in range(nch)]
    lsl_name = args.lsl_name.strip() or f"BF-{args.board}"
    lsl_sid = args.lsl_source_id.strip() or f"bf-{args.board}-{uuid.uuid4().hex[:8]}"
    units = "V" if args.to_volts else "uV"

    info = _build_lsl_info(
        name=lsl_name, nch=nch, sf=sf, source_id=lsl_sid, ch_names=ch_names,
        units=units, meta={"board_id": board_id, "board": args.board}
    )
    outlet = StreamOutlet(info, chunk_size=args.chunk, max_buffered=360)
    print(f"[BF→LSL] Publie LSL: {lsl_name}/EEG — {nch}ch @ {sf:.0f}Hz (sid={lsl_sid}) | units={units}")

    stop = False

    def _sig_handler(*_a):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    scale = 1e-6 if args.to_volts else 1.0
    last_print = 0.0

    try:
        while not stop:
            # Récupère tout ce qui est dispo; on émet par chunks variables (LSL l'accepte)
            data = board.get_board_data()  # shape: (n_rows, N)
            if data is None or data.size == 0:
                time.sleep(0.01)
                continue

            eeg = data[eeg_rows, :].T  # (N, nch)
            if eeg.ndim == 1:
                eeg = eeg[:, None]
            eeg = (eeg * scale).astype(np.float32, copy=False)

            # Pousse par paquets de args.chunk pour régulariser le débit
            N = eeg.shape[0]
            if N <= 0:
                continue
            step = max(1, int(args.chunk))
            for i in range(0, N, step):
                outlet.push_chunk(eeg[i:i+step, :].tolist())

            now = time.time()
            if now - last_print > 1.0:
                print(f"[BF→LSL] push {N} samples (chunk={args.chunk})")
                last_print = now

            # pacing léger (le buffer BrainFlow est en pull; inutile de dormir trop)
            time.sleep(0.002)

    finally:
        print("\n[BF→LSL] Arrêt…")
        try:
            board.stop_stream()
        except Exception:
            pass
        try:
            board.release_session()
        except Exception:
            pass
        print("[BF→LSL] Bye.")
        

if __name__ == "__main__":
    main()
