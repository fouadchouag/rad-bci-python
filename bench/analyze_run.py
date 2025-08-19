import sys, re, numpy as np, pandas as pd

def parse_log(path):
    rows=[]
    with open(path,'r',encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if not line: continue
            parts=line.split(',',2)
            ts=int(parts[0]); ev=parts[1]; payload=parts[2] if len(parts)>2 else ""
            rows.append((ts,ev,payload))
    df=pd.DataFrame(rows,columns=['ts_us','ev','payload']).sort_values('ts_us')
    return df

def get_ttfp(df):
    starts=df[df.ev=='START_TTFP']['ts_us'].to_list()
    if not starts: return None
    start=starts[-1]
    f=df[(df.ev=='FIRST_FRAME') & (df.ts_us>start)]['ts_us']
    return (f.iloc[0]-start)/1e6 if not f.empty else None

def latencies_ms(df):
    ch=df[df.ev=='PARAM_CHANGE']['ts_us'].to_list()
    fr=df[df.ev=='FRAME']['ts_us'].to_list()
    lat=[]; j=0
    for t in ch:
        while j<len(fr) and fr[j]<t: j+=1
        if j<len(fr): lat.append((fr[j]-t)/1e3)
    return np.array(lat,float)

def throughput_sps(df):
    s=df[df.ev=='SAMPLES_IN']
    if len(s)<2: return None
    t1=int(s.iloc[0]['ts_us']); c1=int(re.findall(r'\d+',s.iloc[0]['payload'])[0])
    t2=int(s.iloc[-1]['ts_us']); c2=int(re.findall(r'\d+',s.iloc[-1]['payload'])[0])
    dur=(t2-t1)/1e6;  return (c2-c1)/dur if dur>0 else None

def drop_pct(df):
    st=df[df.ev=='FRAMES_STAT']
    if st.empty: return None
    r,e=map(int, st.iloc[-1]['payload'].strip('"').split(','))
    return 100.0*max(e-r,0)/max(e,1)

def fps(df):
    fr=df[df.ev=='FRAME']['ts_us']
    if fr.empty: return None
    dur=(fr.iloc[-1]-fr.iloc[0])/1e6
    return len(fr)/dur if dur>0 else None

if __name__=="__main__":
    if len(sys.argv)<3:
        print("Usage: python analyze_run.py <log.csv> <SR_Hz>"); sys.exit(1)
    df=parse_log(sys.argv[1]); SR=float(sys.argv[2])
    ttfp=get_ttfp(df); lat=latencies_ms(df); thru=throughput_sps(df)
    drops=drop_pct(df); f=fps(df)
    print(f"TTFP(s)={ttfp:.2f}" if ttfp is not None else "TTFP(s)=NA")
    if len(lat):
        print(f"Latency P50(ms)={np.percentile(lat,50):.2f}")
        print(f"Latency P95(ms)={np.percentile(lat,95):.2f}")
        print(f"n(changes)={len(lat)}")
    else:
        print("Latency P50(ms)=NA\nLatency P95(ms)=NA\nn(changes)=0")
    if thru is not None:
        print(f"Throughput(sps)={thru:.2f}")
        print(f"Thru(% of input)={100.0*thru/SR:.2f}")
    else:
        print("Throughput(sps)=NA\nThru(% of input)=NA")
    print(f"Dropped(%)={drops:.2f}" if drops is not None else "Dropped(%)=NA")
    print(f"FPS={f:.2f}" if f is not None else "FPS=NA")
