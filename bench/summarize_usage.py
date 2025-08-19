# summarize_usage.py
import sys, numpy as np, pandas as pd
df=pd.read_csv(sys.argv[1])
cpu=df['cpu_total_pct'].astype(float); ram=df['rss_total_mib'].astype(float)
print(f"CPU mean={cpu.mean():.1f}% / P95={np.percentile(cpu,95):.1f}% | "
      f"RAM mean={ram.mean():.1f} / P95={np.percentile(ram,95):.1f} MiB | n={len(df)}")
