"""
diagnose_lsl.py
===============

Diagnostic tool to investigate why BCI2000's LSLSource cannot find
our BenchmarkSource stream.

This script replicates exactly what BCI2000 does (resolve_byprop with
property="type", value="EEG") and also does a broader discovery so we
can see what's happening.

Run this with sim_eeg_lsl.py ALREADY RUNNING in another terminal.
"""

import time
from pylsl import resolve_streams, resolve_byprop, library_info


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# --- Test 0: what version of liblsl is pylsl using? ---
section("0. pylsl / liblsl version info")
try:
    print(f"library_info(): {library_info()}")
except Exception as e:
    print(f"library_info() failed: {e}")

# --- Test 1: discover ALL streams (no filter) ---
section("1. Discovering ALL LSL streams (5-second window)")
print("Calling resolve_streams(wait_time=5.0)...")
all_streams = resolve_streams(wait_time=5.0)
print(f"Found {len(all_streams)} stream(s)")
for i, info in enumerate(all_streams):
    print(f"\n  Stream #{i}:")
    print(f"    name         = '{info.name()}'")
    print(f"    type         = '{info.type()}'")
    print(f"    source_id    = '{info.source_id()}'")
    print(f"    channel_count= {info.channel_count()}")
    print(f"    sampling_rate= {info.nominal_srate()}")
    print(f"    channel_format= {info.channel_format()}")
    print(f"    hostname     = '{info.hostname()}'")
    print(f"    uid          = '{info.uid()}'")

# --- Test 2: exactly what BCI2000 does ---
section("2. Exact BCI2000 query: resolve_byprop(type='EEG', timeout=5s)")
try:
    eeg_streams = resolve_byprop("type", "EEG", timeout=5.0)
    print(f"Found {len(eeg_streams)} stream(s) with type='EEG'")
    for info in eeg_streams:
        print(f"  -> '{info.name()}' (type='{info.type()}')")
except Exception as e:
    print(f"resolve_byprop failed: {e}")

# --- Test 3: try resolving by name instead ---
section("3. Alternative query: resolve_byprop(name='BenchmarkSource')")
try:
    name_streams = resolve_byprop("name", "BenchmarkSource", timeout=5.0)
    print(f"Found {len(name_streams)} stream(s) with name='BenchmarkSource'")
    for info in name_streams:
        print(f"  -> '{info.name()}' (type='{info.type()}')")
except Exception as e:
    print(f"resolve_byprop failed: {e}")

# --- Interpretation guide ---
section("INTERPRETATION")
if not all_streams:
    print("NO STREAMS AT ALL visible.")
    print("Possible causes:")
    print("  A) sim_eeg_lsl.py is not running right now")
    print("  B) Windows Firewall is blocking LSL multicast on loopback")
    print("  C) Multiple network interfaces confusing LSL resolver")
    print("")
    print("Next step: ensure sim_eeg_lsl.py terminal shows 'Start at...'")
    print("           and this diagnostic is started WITHIN 2 minutes after.")
else:
    names = [s.name() for s in all_streams]
    types = [s.type() for s in all_streams]
    if "BenchmarkSource" in names:
        idx = names.index("BenchmarkSource")
        detected_type = types[idx]
        print(f"BenchmarkSource IS visible with type='{detected_type}'")
        if detected_type == "EEG":
            print("Type is 'EEG' -> BCI2000 should be able to find it.")
            print("If BCI2000 still fails: LIBRARY VERSION MISMATCH between")
            print("pylsl and BCI2000's liblsl.dll is the most likely cause.")
        else:
            print(f"Type is '{detected_type}' (not 'EEG') -> BCI2000 can't see it!")
            print("Fix: modify sim_eeg_lsl.py constant STREAM_TYPE to 'EEG'")
    else:
        print(f"BenchmarkSource NOT in stream list; found instead: {names}")
        print("Fix: restart sim_eeg_lsl.py")
