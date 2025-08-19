# ps_logger_tree.py
import argparse, csv, time, psutil, os
def mib(b): return b/(1024*1024)
def prime(ps, dt):
    for p in [ps]+ps.children(recursive=True):
        try: p.cpu_percent(None)
        except: pass
    time.sleep(dt)
def sample(ps):
    cpu=rss=0.0
    for p in [ps]+ps.children(recursive=True):
        try:
            cpu += p.cpu_percent(None)
            rss += p.memory_info().rss
        except: pass
    return cpu, mib(rss)
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--hz",type=float,default=5.0)
    ap.add_argument("--label",type=str,default="W1")
    ap.add_argument("--out",type=str,default="host_usage.csv")
    a=ap.parse_args()
    ps=psutil.Process(a.pid); dt=1.0/a.hz
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    prime(ps, dt)
    with open(a.out,"w",newline="") as f:
        w=csv.writer(f); w.writerow(["t","label","cpu_total_pct","rss_total_mib"])
        try:
            while True:
                cpu,ram = sample(ps)
                w.writerow([time.time(), a.label, f"{cpu:.2f}", f"{ram:.2f}"]); f.flush()
                time.sleep(dt)
        except KeyboardInterrupt:
            pass
