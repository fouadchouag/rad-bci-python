// external_scripts/double.js

const fs = require('fs');

// Lire le fichier input.json
let input = JSON.parse(fs.readFileSync('input.json', 'utf-8'));

// Afficher dans la console pour debug
console.log("📥 Input reçu :", input);

// Calculer la sortie
let output = {
    output1: input.input1 * 20  // ⚠️ DOIT être appelé "value"
};

// Sauvegarder le résultat dans output.json
fs.writeFileSync('output.json', JSON.stringify(output));
