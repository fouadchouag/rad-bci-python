# I/O Types and Conventions

| dtype        | Meaning / Shape                   | Notes |
|--------------|-----------------------------------|-------|
| `ndarray_2d` | 2D float array `[ch x samples]`   | JSON as nested lists; NumPy in-process. |
| `mne_raw`    | `mne.io.Raw`                      | Wrapper converts to `ndarray_2d` and infers `sfreq`. |
| `sfreq`      | Sampling rate (float, Hz)         | Required for time-domain ops. |
| `float/int/bool/str` | Scalars                    | Parameters or simple values. |
| `json`       | Arbitrary JSON object             | For structured metadata. |
| `path`       | Filesystem path                   | OS portable.

**Conventions**
- Use `raw` for EEG signal matrices.
- Optional inputs start with `opt_` (e.g., `opt_annotations`).
- If you output `raw` and know `sfreq`, include it in the result; wrapper can reconstruct `mne.Raw`.
