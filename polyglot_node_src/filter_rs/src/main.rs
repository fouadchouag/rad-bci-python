use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::fs;

#[derive(Deserialize)]
struct InputPayload {
    #[serde(default)]
    raw: Vec<Vec<f32>>,     // [C][N]
    #[serde(default)]
    sfreq: Option<f32>,     // Hz
    #[serde(default)]
    low: Option<f32>,       // Hz (HP)
    #[serde(default)]
    high: Option<f32>,      // Hz (LP)
    #[serde(default)]
    notch: Option<String>,  // "off" | "50" | "60" | "<freq>"
    #[serde(default)]
    q: Option<f32>,         // facteur Q pour le notch
}

#[derive(Serialize)]
struct OutputPayload {
    raw: Vec<Vec<f32>>,     // [C][N]
}

fn main() {
    // --- args: --in <file> --out <file> ---
    let args: Vec<String> = env::args().collect();
    let in_path = get_arg(&args, "--in").expect("missing --in <path>");
    let out_path = get_arg(&args, "--out").expect("missing --out <path>");

    // --- read & parse JSON ---
    let s = fs::read_to_string(in_path).expect("cannot read input file");
    let v: Value = serde_json::from_str(&s).expect("invalid JSON");

    // Tolérant: si l'appelant n'a pas exactement le mapping InputPayload,
    // on pioche à la main avec des défauts raisonnables.
    let mut inp = parse_input(v);

    // --- paramètres ---
    let fs_hz = inp.sfreq.unwrap_or(250.0).max(1.0);
    let nyq = fs_hz * 0.5;
    let hp_hz = inp.low.unwrap_or(0.0).clamp(0.0, nyq - 1e-6);
    let lp_hz = inp.high.unwrap_or(0.0).clamp(0.0, nyq - 1e-6);

    // Notch
    let mut notch_hz: f32 = 0.0;
    if let Some(s) = &inp.notch {
        let t = s.trim().to_lowercase();
        if t != "off" && !t.is_empty() {
            notch_hz = t.parse::<f32>().unwrap_or(0.0).clamp(0.0, nyq - 1e-6);
        }
    }
    let q = inp.q.unwrap_or(0.707).clamp(0.1, 10.0);

    // --- traitement canal par canal ---
    let mut out = inp.raw;
    for ch in out.iter_mut() {
        if hp_hz > 0.0 {
            one_pole_highpass_inplace(ch, fs_hz, hp_hz);
        }
        if lp_hz > 0.0 {
            one_pole_lowpass_inplace(ch, fs_hz, lp_hz);
        }
        if notch_hz > 0.0 {
            biquad_notch_inplace(ch, fs_hz, notch_hz, q);
        }
    }

    // --- write JSON ---
    let result = OutputPayload { raw: out };
    let txt = json!(result).to_string();
    fs::write(out_path, txt).expect("cannot write output file");
}

fn get_arg(args: &[String], key: &str) -> Option<String> {
    args.iter()
        .position(|a| a == key)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

// Parse tolérant: récupère "raw" [C][N], "sfreq", "low", "high", "notch", "q".
fn parse_input(v: Value) -> InputPayload {
    // Si possible, désérialisation directe.
    if let Ok(inp) = serde_json::from_value::<InputPayload>(v.clone()) {
        return inp;
    }
    // fallback manuel
    let obj = v.as_object().cloned().unwrap_or_default();
    let raw = obj
        .get("raw")
        .and_then(|x| x.as_array())
        .map(|ch| {
            ch.iter()
                .map(|row| row.as_array()
                    .map(|r| r.iter().map(|z| z.as_f64().unwrap_or(0.0) as f32).collect())
                    .unwrap_or_else(|| vec![])
                )
                .collect::<Vec<Vec<f32>>>()
        })
        .unwrap_or_else(|| vec![]);

    let sfreq = obj.get("sfreq").and_then(|x| x.as_f64()).map(|f| f as f32);
    let low   = obj.get("low").and_then(|x| x.as_f64()).map(|f| f as f32);
    let high  = obj.get("high").and_then(|x| x.as_f64()).map(|f| f as f32);
    let notch = obj.get("notch").and_then(|x| if x.is_string() { x.as_str().map(|s| s.to_string()) } else { x.as_f64().map(|f| format!("{}", f)) });
    let q     = obj.get("q").and_then(|x| x.as_f64()).map(|f| f as f32);

    InputPayload { raw, sfreq, low, high, notch, q }
}

// ----------- DSP très simple, suffisant pour la démo -----------

// LP 1er ordre (constante de temps RC)
fn one_pole_lowpass_inplace(x: &mut [f32], fs: f32, fc: f32) {
    if x.is_empty() || fc <= 0.0 { return; }
    let dt = 1.0 / fs;
    let rc = 1.0 / (2.0 * std::f32::consts::PI * fc);
    let alpha = dt / (rc + dt); // [0..1]
    let mut y_prev = x[0];
    for i in 0..x.len() {
        let xi = x[i];
        let y = y_prev + alpha * (xi - y_prev);
        x[i] = y;
        y_prev = y;
    }
}

// HP 1er ordre via forme récursive
fn one_pole_highpass_inplace(x: &mut [f32], fs: f32, fc: f32) {
    if x.len() < 2 || fc <= 0.0 { return; }
    let dt = 1.0 / fs;
    let rc = 1.0 / (2.0 * std::f32::consts::PI * fc);
    let alpha = rc / (rc + dt); // [0..1]
    let mut y_prev = 0.0_f32;
    let mut x_prev = x[0];
    for i in 0..x.len() {
        let xi = x[i];
        let y = alpha * (y_prev + xi - x_prev);
        x[i] = y;
        y_prev = y;
        x_prev = xi;
    }
}

// Notch biquad standard (f0, Q)
fn biquad_notch_inplace(x: &mut [f32], fs: f32, f0: f32, q: f32) {
    if x.len() < 3 || f0 <= 0.0 { return; }
    let w0 = 2.0 * std::f32::consts::PI * (f0 / fs);
    let cosw0 = w0.cos();
    let alpha = w0.sin() / (2.0 * q.max(1e-6));

    // Coeffs
    let b0 = 1.0;
    let b1 = -2.0 * cosw0;
    let b2 = 1.0;
    let a0 = 1.0 + alpha;
    let a1 = -2.0 * cosw0;
    let a2 = 1.0 - alpha;

    // Normalisation (a0)
    let b0n = b0 / a0;
    let b1n = b1 / a0;
    let b2n = b2 / a0;
    let a1n = a1 / a0;
    let a2n = a2 / a0;

    // Direct Form I
    let mut x1 = 0.0_f32; let mut x2 = 0.0_f32;
    let mut y1 = 0.0_f32; let mut y2 = 0.0_f32;

    for n in 0..x.len() {
        let xn = x[n];
        let y = b0n * xn + b1n * x1 + b2n * x2 - a1n * y1 - a2n * y2;
        x2 = x1; x1 = xn;
        y2 = y1; y1 = y;
        x[n] = y;
    }
}
