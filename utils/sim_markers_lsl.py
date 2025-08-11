# sim_markers_lsl.py
import time, random, signal
from pylsl import StreamInfo, StreamOutlet, local_clock

info = StreamInfo('SimMarkers', 'Markers', 1, 0, 'string', 'simmarkers-001')
outlet = StreamOutlet(info)
running = True
def stop(*_): 
    global running; running = False
signal.signal(signal.SIGINT, stop)

labels = ['S1', 'S2', 'S3', 'S4']
print("[SimMarkers] Envoi d’événements aléatoires. Ctrl+C pour arrêter.")
while running:
    time.sleep(random.uniform(1.5, 3.5))
    m = random.choice(labels)
    outlet.push_sample([m], timestamp=local_clock())
    print(f"[SimMarkers] {m}")
