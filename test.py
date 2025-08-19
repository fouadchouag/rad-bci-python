from pylsl import resolve_streams, StreamInlet
import time
streams = resolve_streams(1.0)
print("found:", [(s.name(), s.type(), s.channel_count(), int(s.nominal_srate())) for s in streams])
if not streams:
    raise SystemExit("no LSL streams")
s = streams[0]
inlet = StreamInlet(s, max_buflen=10)
inlet.open_stream(1.0)
inlet.time_correction()
t0 = time.time(); n = 0; nrows = 0
while time.time() - t0 < 3.0:
    samples, ts = inlet.pull_chunk(timeout=0.2, max_samples=128)
    nrows += len(samples)
    if samples:
        n += len(samples) * len(samples[0])
print(f"rows={nrows}, values={n}")