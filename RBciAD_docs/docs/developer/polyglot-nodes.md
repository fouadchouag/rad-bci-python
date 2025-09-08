# Polyglot Nodes (Python / Rust / Node.js / etc.)

Two ways to run non-Python logic:

## A) In-process (Python only)
Put your algorithm in a `.py` file with a function:
```python
def process(payload: dict) -> dict:
    # payload includes inputs + params
    return {"raw": ...}  # outputs by name
```
Set **Exec mode** to `auto` or `inprocess`. Wrapper calls `process(payload)` directly (fast, no JSON).

## B) Subprocess (polyglot)
Your program should support **one** (preferably both) protocol(s):

### 1) Persistent `--stdio` (recommended)
- Start: wrapper spawns `your_binary --stdio`.
- I/O: one **JSON line** in, one **JSON line** out.

**Node.js template:**
```js
#!/usr/bin/env node
const readline = require("readline");
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let data = {}; try { data = JSON.parse(line); } catch {}
  // TODO: compute result from data
  const result = { /* "raw": [[...],[...]], "sfreq": 250 */ };
  process.stdout.write(JSON.stringify(result) + "\n");
});
```

**Rust template:**
```rust
use std::io::{self, BufRead, Write};
use serde_json;
fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    for line in stdin.lock().lines() {
        if let Ok(s) = line {
            if s.trim().is_empty() { continue; }
            let data: serde_json::Value = serde_json::from_str(&s).unwrap_or_default();
            let result = serde_json::json!({ /* "raw": [[..],[..]] */ });
            writeln!(stdout, "{}", result.to_string()).ok();
            stdout.flush().ok();
        }
    }
}
```

### 2) File mode `--in/--out` (fallback)
- Wrapper writes `input.json` and runs:  
  `your_binary --in input.json --out output.json`
- Your program reads `--in` and writes `--out` JSON.

**Python template:**
```python
import json, sys, argparse
ap = argparse.ArgumentParser()
ap.add_argument("--in", dest="in_path"); ap.add_argument("--out", dest="out_path")
args = ap.parse_args()
data = json.load(open(args.in_path, "r", encoding="utf-8"))
# TODO: compute
json.dump({}, open(args.out_path, "w", encoding="utf-8"))
```

### JSON payload
- Inputs by name (e.g., `"raw": [[C][N]]`, `"sfreq": 250.0`), plus parameters (`"low": 1.0`).
- Output keys must match the node's declared **outputs**.
