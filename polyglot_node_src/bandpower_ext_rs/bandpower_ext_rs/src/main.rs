use std::{env, fs};
use std::collections::HashMap;
use num_complex::Complex64 as C;
use rustfft::FftPlanner;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct Input {
    segment: Vec<Vec<f64>>,           // n_ch x n_samples
    sfreq: f64,
    ch_names: Vec<String>,
    #[serde(default)]
    bands: HashMap<String, [f64; 2]>, // nom -> [fmin, fmax]
}

#[derive(Serialize)]
struct Output {
    features: HashMap<String, HashMap<String, f64>>,
    band_labels: Vec<String>,
}

fn hann(n: usize) -> Vec<f64> {
    if n <= 1 { return vec![1.0; n]; }
    (0..n)
        .map(|i| 0.5 * (1.0 - (2.0 * std::f64::consts::PI * i as f64 / (n as f64 - 1.0)).cos()))
        .collect()
}

fn bandpower_one(x: &[f64], sfreq: f64, bands: &HashMap<String, [f64; 2]>) -> HashMap<String, f64> {
    let n = x.len();
    if n <= 1 || sfreq <= 0.0 {
        return bands.keys().map(|k| (k.clone(), f64::NAN)).collect();
    }

    // Fenêtre Hann + buffer complexe (in-place)
    let w = hann(n);
    let mut buf: Vec<C> = x.iter().zip(w.iter()).map(|(xi, wi)| C::new(xi * wi, 0.0)).collect();

    // FFT in-place
    let mut planner = FftPlanner::<f64>::new();
    let fft = planner.plan_fft_forward(n);
    fft.process(&mut buf);

    // PSD ~ |X|^2 / N, ne garder que 0..N/2 (spectre réel)
    let nhalf = n / 2;
    let psd: Vec<f64> = buf.iter()
        .take(nhalf + 1)
        .map(|c| c.norm_sqr() / n as f64)
        .collect();
    let freqs: Vec<f64> = (0..=nhalf).map(|k| (k as f64) * sfreq / (n as f64)).collect();

    // Moyenne par bande
    let mut out = HashMap::new();
    for (name, [fmin, fmax]) in bands.iter() {
        let mut sum = 0.0;
        let mut cnt = 0usize;
        for (k, f) in freqs.iter().enumerate() {
            if *f >= *fmin && *f < *fmax {
                sum += psd[k];
                cnt += 1;
            }
        }
        out.insert(name.clone(), if cnt > 0 { sum / (cnt as f64) } else { f64::NAN });
    }
    out
}

fn main() {
    // args: --input in.json --output out.json
    let args: Vec<String> = env::args().collect();
    let mut input_path = String::new();
    let mut output_path = String::new();
    let mut i = 1;
    while i + 1 < args.len() {
        match args[i].as_str() {
            "--input" => input_path = args[i + 1].clone(),
            "--output" => output_path = args[i + 1].clone(),
            _ => {}
        }
        i += 2;
    }
    if input_path.is_empty() || output_path.is_empty() {
        eprintln!("Usage: bandpower_ext_rs --input in.json --output out.json");
        std::process::exit(1);
    }

    let txt = fs::read_to_string(&input_path).expect("read input");
    let mut inp: Input = serde_json::from_str(&txt).expect("parse json");

    // Bandes par défaut si absentes
    if inp.bands.is_empty() {
        inp.bands.insert("delta".into(), [1.0, 4.0]);
        inp.bands.insert("theta".into(), [4.0, 8.0]);
        inp.bands.insert("alpha".into(), [8.0, 13.0]);
        inp.bands.insert("beta".into(),  [13.0, 30.0]);
        inp.bands.insert("gamma".into(), [30.0, 45.0]);
    }

    let mut features = HashMap::new();
    for (i, ch) in inp.segment.iter().enumerate() {
        let name = inp.ch_names.get(i).cloned().unwrap_or_else(|| format!("ch{}", i));
        features.insert(name, bandpower_one(ch, inp.sfreq, &inp.bands));
    }

    let out = Output {
        features,
        band_labels: inp.bands.keys().cloned().collect(),
    };
    let out_txt = serde_json::to_string(&out).expect("to json");
    if let Some(dir) = std::path::Path::new(&output_path).parent() {
        let _ = fs::create_dir_all(dir);
    }
    fs::write(&output_path, out_txt).expect("write output");

    println!("[bandpower_ext] OK (rs): {} ch, fs={:.2}", inp.segment.len(), inp.sfreq);
}
