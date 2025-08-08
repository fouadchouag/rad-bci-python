use std::fs;
use std::path::Path;
use std::io::Read;
use std::io::Write;

fn main() {
    // ⚠️ Bien mettre le même nom que le plugin RBciAD : triplers
    let input_path = Path::new("temp_io/input_triplers.json");
    let output_path = Path::new("temp_io/output_triplers.json");

    let mut file = fs::File::open(input_path).expect("Impossible d'ouvrir input");
    let mut contents = String::new();
    file.read_to_string(&mut contents).unwrap();

    let input_data: serde_json::Value = serde_json::from_str(&contents).unwrap();
    let input_val = input_data["input1"].as_f64().unwrap_or(0.0);

    let output_val = input_val * 3.0;
    let output_data = serde_json::json!({ "output1": output_val });

    let mut out_file = fs::File::create(output_path).expect("Erreur création output");
    out_file.write_all(output_data.to_string().as_bytes()).unwrap();
}
