const fs = require('fs');
const path = require('path');

// 🔧 Corrigé : base = dossier où tu lances `node`
const basePath = process.cwd();
const inputPath = path.join(basePath, 'temp_io', 'input_doublerjs.json');
const outputPath = path.join(basePath, 'temp_io', 'output_doublerjs.json');

// Lire les données
const rawInput = fs.readFileSync(inputPath);
const data = JSON.parse(rawInput);

console.log("📥 Input reçu :", data);

// Traitement
const value = data.input1 ?? 0;
const result = { output1: value * 2 };

// Écrire le résultat
fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
