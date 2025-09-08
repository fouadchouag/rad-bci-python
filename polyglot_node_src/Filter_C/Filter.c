// === RawFilter_C — C CLI bandpass (HP@low → LP@high) ======================
// Usage: raw_filter_c.exe --in input.json --out output.json
//
// JSON attendu (entrée):
// {
//   "raw":  [[...],[...]],   // [C][N] (C=canaux, N=échantillons), float
//   "sfreq": 250.0,          // Hz
//   "low":   1.0,            // optionnel (Hz)   - par défaut 1.0
//   "high":  40.0,           // optionnel (Hz)   - par défaut 40.0
//   "q_low": 0.7071,         // optionnel        - par défaut 0.7071
//   "q_high":0.7071          // optionnel        - par défaut 0.7071
// }
//
// JSON produit (sortie):
// {
//   "raw": [[...],[...]]     // [C][N], filtré
// }
//
// Dépendance JSON: parson (MIT) — ajoutez parson.h/parson.c dans le projet.
//   https://github.com/kgabis/parson (ou copiez parson.h/.c à côté de ce fichier)
//
// Compilation (Windows MSVC):
//   cl /O2 /MD raw_filter_c.c parson.c /Fe:raw_filter_c.exe
// MinGW / Linux:
//   gcc -O3 -std=c11 raw_filter_c.c parson.c -o raw_filter_c -lm
// ==========================================================================

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "parson.h"   // JSON

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

//-------------- utils args --------------
static const char* find_arg(int argc, char** argv, const char* key) {
    for (int i = 0; i < argc - 1; ++i) {
        if (strcmp(argv[i], key) == 0) return argv[i+1];
    }
    return NULL;
}

//-------------- clamp freq --------------
static float clamp_freq(float f, float fs) {
    float nyq = fs * 0.5f - 1e-6f;
    if (f < 0.01f) f = 0.01f;
    if (f > nyq)   f = nyq;
    return f;
}

//-------------- Biquad ------------------
typedef struct {
    float b0, b1, b2, a1, a2;
    float z1, z2;
} Biquad;

static inline float biquad_process(Biquad* s, float x) {
    // Direct Form I (transposed) — stable et rapide
    float y = s->b0 * x + s->z1;
    s->z1   = s->b1 * x - s->a1 * y + s->z2;
    s->z2   = s->b2 * x - s->a2 * y;
    return y;
}

static Biquad biquad_lowpass(float fs, float f0, float q) {
    float w0 = 2.0f * (float)M_PI * f0 / fs;
    float cosw = cosf(w0), sinw = sinf(w0);
    float alpha = sinw / (2.0f * q);

    float b0 = (1.0f - cosw) * 0.5f;
    float b1 = 1.0f - cosw;
    float b2 = (1.0f - cosw) * 0.5f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosw;
    float a2 = 1.0f - alpha;

    Biquad s = { b0/a0, b1/a0, b2/a0, a1/a0, a2/a0, 0.0f, 0.0f };
    return s;
}

static Biquad biquad_highpass(float fs, float f0, float q) {
    float w0 = 2.0f * (float)M_PI * f0 / fs;
    float cosw = cosf(w0), sinw = sinf(w0);
    float alpha = sinw / (2.0f * q);

    float b0 = (1.0f + cosw) * 0.5f;
    float b1 = -(1.0f + cosw);
    float b2 = (1.0f + cosw) * 0.5f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosw;
    float a2 = 1.0f - alpha;

    Biquad s = { b0/a0, b1/a0, b2/a0, a1/a0, a2/a0, 0.0f, 0.0f };
    return s;
}

//-------------- Lecture JSON ------------
typedef struct {
    // données sous forme [C][N] contiguës (flat), plus tailles
    float* data;  // taille C*N
    size_t C, N;
    float sfreq, low, high, q_low, q_high;
} InputData;

static void free_input(InputData* in) {
    if (!in) return;
    free(in->data);
    in->data = NULL;
}

static int read_input_json(const char* in_path, InputData* out) {
    memset(out, 0, sizeof(*out));
    out->low    = 1.0f;
    out->high   = 40.0f;
    out->q_low  = 0.7071f;
    out->q_high = 0.7071f;

    JSON_Value* root = json_parse_file(in_path);
    if (!root) { fprintf(stderr, "JSON parse error: %s\n", in_path); return 0; }
    JSON_Object* obj = json_value_get_object(root);

    out->sfreq = (float)json_object_get_number(obj, "sfreq");
    if (out->sfreq <= 0.0f) {
        json_value_free(root);
        fprintf(stderr, "sfreq missing/invalid\n");
        return 0;
    }
    double low  = json_object_get_number(obj, "low");   if (low  > 0) out->low  = (float)low;
    double high = json_object_get_number(obj, "high");  if (high > 0) out->high = (float)high;
    double ql   = json_object_get_number(obj, "q_low"); if (ql   > 0) out->q_low  = (float)ql;
    double qh   = json_object_get_number(obj, "q_high");if (qh   > 0) out->q_high = (float)qh;

    JSON_Array* raw = json_object_get_array(obj, "raw");
    if (!raw) { json_value_free(root); fprintf(stderr, "raw missing\n"); return 0; }

    size_t C = json_array_get_count(raw);
    if (C == 0) { json_value_free(root); fprintf(stderr, "raw has zero channels\n"); return 0; }

    // On vérifie la longueur N à partir du premier canal
    JSON_Array* ch0 = json_array_get_array(raw, 0);
    if (!ch0) { json_value_free(root); fprintf(stderr, "raw[0] not an array\n"); return 0; }
    size_t N = json_array_get_count(ch0);
    if (N == 0) { json_value_free(root); fprintf(stderr, "raw[0] empty\n"); return 0; }

    // Alloue buffer contigu [C][N]
    float* data = (float*)malloc(sizeof(float) * C * N);
    if (!data) { json_value_free(root); fprintf(stderr, "OOM\n"); return 0; }

    // Remplit data[c*N + i] depuis JSON
    for (size_t c = 0; c < C; ++c) {
        JSON_Array* ch = json_array_get_array(raw, c);
        if (!ch) { free(data); json_value_free(root); fprintf(stderr, "raw[%zu] not array\n", c); return 0; }
        if (json_array_get_count(ch) != N) {
            free(data); json_value_free(root); fprintf(stderr, "raw[%zu] length mismatch\n", c); return 0;
        }
        for (size_t i = 0; i < N; ++i) {
            double v = json_array_get_number(ch, i);
            data[c*N + i] = (float)v;
        }
    }

    out->data = data;
    out->C = C;
    out->N = N;

    json_value_free(root);
    return 1;
}

//-------------- Écriture JSON -----------
static int write_output_json(const char* out_path, const float* data, size_t C, size_t N) {
    JSON_Value* root = json_value_init_object();
    JSON_Object* obj = json_value_get_object(root);

    JSON_Value* arr_raw_v = json_value_init_array();
    JSON_Array* arr_raw   = json_value_get_array(arr_raw_v);

    for (size_t c = 0; c < C; ++c) {
        JSON_Value* ch_v = json_value_init_array();
        JSON_Array* ch   = json_value_get_array(ch_v);
        const float* line = data + c*N;
        for (size_t i = 0; i < N; ++i) {
            json_array_append_number(ch, (double)line[i]);
        }
        json_array_append_value(arr_raw, ch_v);
    }
    json_object_set_value(obj, "raw", arr_raw_v);

    int ok = (json_serialize_to_file_pretty(root, out_path) == JSONSuccess);
    json_value_free(root);
    return ok;
}

//-------------- Main --------------------
int main(int argc, char** argv) {
    const char* in_path  = find_arg(argc, argv, "--in");
    const char* out_path = find_arg(argc, argv, "--out");
    if (!in_path || !out_path) {
        fprintf(stderr, "Usage: %s --in input.json --out output.json\n", argv[0]);
        return 1;
    }

    InputData in;
    if (!read_input_json(in_path, &in)) {
        return 2;
    }

    float fs    = in.sfreq;
    float low   = clamp_freq(in.low,  fs);
    float high  = clamp_freq(in.high, fs);
    float ql    = (in.q_low  > 0.0f) ? in.q_low  : 0.7071f;
    float qh    = (in.q_high > 0.0f) ? in.q_high : 0.7071f;

    // Cas limites: si low >= high, on fait un passe-bande dégénéré (ou on bypass)
    if (low >= high) {
        // bypass
        int ok_bypass = write_output_json(out_path, in.data, in.C, in.N);
        free_input(&in);
        return ok_bypass ? 0 : 3;
    }

    // Prépare un HP puis un LP par canal
    Biquad* hp = (Biquad*)malloc(sizeof(Biquad) * in.C);
    Biquad* lp = (Biquad*)malloc(sizeof(Biquad) * in.C);
    if (!hp || !lp) {
        fprintf(stderr, "OOM biquads\n");
        free(hp); free(lp); free_input(&in);
        return 4;
    }
    for (size_t c = 0; c < in.C; ++c) {
        hp[c] = biquad_highpass(fs, low,  ql);
        lp[c] = biquad_lowpass (fs, high, qh);
    }

    // Filtrage in-place sur [C][N]
    for (size_t c = 0; c < in.C; ++c) {
        float* x = in.data + c*in.N;
        for (size_t i = 0; i < in.N; ++i) {
            float y = biquad_process(&hp[c], x[i]);
            float z = biquad_process(&lp[c], y);
            x[i] = z;
        }
    }

    // Écrit la sortie
    int ok = write_output_json(out_path, in.data, in.C, in.N);

    free(hp); free(lp);
    free_input(&in);

    return ok ? 0 : 5;
}
