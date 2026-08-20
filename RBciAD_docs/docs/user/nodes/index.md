# Nodes Catalog

> Auto-generated from plugin `help` dicts. Use Shift+F1 on a node to open its page.

## Analysis

| Node | Summary |
|---|---|
| [PSDWelch](./psdwelch.md) | Compute power spectral density via Welch's method from MNE Raw/Epochs or a raw segment array. |

## BCI/Feedback

| Node | Summary |
|---|---|
| [BCI_BallController](./bci_ballcontroller.md) | Controls a 2D ball using classifier predictions. Maps pred_idx to directional actions (Left/Right/Up/Down/Idle) with physics simulation (velocity, friction, boundary bouncing). Supports confidence-weighted speed. |

## BCI/Utils

| Node | Summary |
|---|---|
| [BCI_CommandRouter](./bci_commandrouter.md) | Transforms classifier predictions into stable directional commands (LEFT/RIGHT/UP/DOWN/STOP) with confidence threshold, dwell time, majority smoothing, and refractory period. Optionally emits an LSL stream. |
| [BCI_Config](./bci_config.md) | No-code workflow config manager: scans all nodes in the workflow, provides a friendly UI to edit their parameters (auto-generated from export_config/config_hints), and supports preview/revert/apply (selected/class/all) plus preset save/load. |
| [BCI_MetricsViewer](./bci_metricsviewer.md) | Displays trained model evaluation metrics from a BCI_Trainer report: CV accuracy ± std, balanced accuracy, F1 macro, confusion matrix, and per-class accuracy. Supports JSON and CSV export. |
| [BCI_OnlineMetrics](./bci_onlinemetrics.md) | Computes online rolling accuracy and cumulative confusion matrix by comparing pred_idx vs y_idx in real time. |
| [BCICollector](./bcicollector.md) | Collect features and labels into a dataset dict for training. Supports manual recording or marker-based assignment. |
| [OnlineMetrics](./onlinemetrics.md) | Computes online metrics by comparing pred_idx vs y_idx: rolling accuracy (window N), cumulative accuracy, Cohen's kappa, and cumulative confusion matrix. Auto-expands K when new class indices appear. |
| [{...}Hz](./hz.md) | Convertit des marqueurs LSL (strings) en y_idx (int) et y_name (str). |

## Custom

| Node | Summary |
|---|---|
| [_BigDlg](./_bigdlg.md) | MNEICAViewer (simple & robuste) |
| [CollapsibleSection](./collapsiblesection.md) | BandPowerExtractor |
| [CollapsibleSection](./collapsiblesection.md) | Visualize signals, features or predictions. |
| [RawfilterCPlugin](./rawfiltercplugin.md) | RawFilter_C: custom node. |

## Features

| Node | Summary |
|---|---|
| [BandPowerExtractor](./bandpowerextractor.md) | Aggregate PSD into canonical frequency bands (delta/theta/alpha/beta/gamma) as absolute or relative power. |
| [PSDBandFeaturesLite](./psdbandfeatureslite.md) | Compute per-band power features from precomputed frequency arrays and PSD matrix. |

## Input Nodes

| Node | Summary |
|---|---|
| [AcquisitionManager](./acquisitionmanager.md) | AcquisitionManager (léger) — LSL \| Emulator \| Native (disabled) |
| [Array → MNE Raw](./array-mne-raw.md) | Convert numeric arrays (segment/samples) to an MNE Raw object. |
| [EEGMatReader](./eegmatreader.md) | Read .mat EEG files (BBCI/BCI Competition/generic) and stream segments. |
| [EEGReader](./eegreader.md) | Load EDF EEG files using MNE-Python. Outputs an MNE Raw object. |
| [EEGUniversalReader](./eeguniversalreader.md) | EEGUniversalReader — ultra-fast, tous formats MNE, avec métriques enrichies: |
| [GDFReader](./gdfreader.md) | Read GDF EEG files using MNE-Python; emits an MNE Raw object. |
| [LSL_EEG_Inlet](./lsl_eeg_inlet.md) | Inlet LSL générique pour flux EEG (float32, multi-canaux). |
| [LSL_EEG_Inlet_Fast](./lsl_eeg_inlet_fast.md) | Inlet EEG non-bloquant : thread lecteur + DropOldQueue + QTimer emit. |
| [LSL_Markers_Inlet](./lsl_markers_inlet.md) | Inlet LSL pour flux de marqueurs (strings). |
| [LSLInletPlugin](./lslinletplugin.md) | LSL Inlet — compatible LiveDisplay / SliceFilter |
| [MAT → MNE Raw](./mat-mne-raw.md) | Load .mat EEG files (BBCI/BCI-Compatible) and convert to MNE Raw. |
| [MNEDatasetLoader](./mnedatasetloader.md) | Load EEGBCI dataset and compute per-channel metric + band powers for topomaps. |
| [MNESampleLoader](./mnesampleloader.md) | Load the MNE sample dataset (sample_audvis_raw.fif). |
| [SyntheticLR](./syntheticlr.md) | Generate synthetic Left/Right motor-imagery EEG with streaming support. |

## ML

| Node | Summary |
|---|---|
| [BCI_Features](./bci_features.md) | Extract EEG features: PSD band power, ERP mean windows, or time-domain statistics. |
| [BCI_Predictor](./bci_predictor.md) | Online BCI predictor: applies a trained model to incoming features and outputs class predictions with confidence. |
| [BCI_Trainer](./bci_trainer.md) | Train a scikit-learn classifier (LogisticRegression or LDA) in a background thread. Outputs a trained model and cross-validation report. |
| [BCI_TSFBCSPFeatures](./bci_tsfbcspfeatures.md) | TS-FBCSP: Filter-bank tangent space features with OAS covariance. |
| [ClassifierMetrics](./classifiermetrics.md) | Evaluates a binary dataset {X, y, y_names} from an upstream EEGClassifier using StratifiedKFold cross-validation with a StandardScaler + LogisticRegression pipeline. Displays accuracy ± std, precision/recall, and confusion matrix. |
| [ClassifierMetrics_1](./classifiermetrics_1.md) | Evaluates a multi-class dataset {X, y, y_names} using StratifiedKFold cross-validation with a StandardScaler + LogisticRegression pipeline. Displays accuracy ± std, macro-F1, and confusion matrix. |
| [ClassifierRuntime](./classifierruntime.md) | Applies a fitted sklearn classifier to a single feature vector, producing pred_idx, pred_label, and optionally a probability dict. |
| [CSPTrainer](./csptrainer.md) | Train a Common Spatial Patterns (CSP) spatial filter from EEG trials and labels. |
| [EEGClassifier](./eegclassifier.md) | 2-class (Left/Right) EEG classifier with record-train-predict workflow. |
| [EEGClassifier_1](./eegclassifier_1.md) | Multi-class (2-6) EEG classifier with record-train-predict workflow and optional auto-feature extraction. |
| [EEGClassifier_2](./eegclassifier_2.md) | Advanced BCI trainer: multi-class (2-8) collect, CV cross-validation, train, predict, and dataset import/export. |
| [RiemannCov](./riemanncov.md) | Compute the SPD covariance matrix from a single EEG segment. |
| [RiemannTSApply](./riemanntsapply.md) | Apply a trained Tangent Space transform to project covariance matrices into 1D feature vectors. |
| [RiemannTSTrainer](./riemanntstrainer.md) | Train a Tangent Space mapping (pyRiemann) from covariance matrices and labels. |

## Output Nodes

| Node | Summary |
|---|---|
| [BallFeedback](./ballfeedback.md) | Moves a ball left/right according to classifier prediction — real-time BCI feedback visualizer. |
| [BandpowerInspector](./bandpowerinspector.md) | Visual inspector for band power features — displays per-channel band powers as a table or bar chart. |
| [EEGLiveDisplay](./eeglivedisplay.md) | Real-time EEG display with scrolling traces. Supports both raw (continuous) and segment modes. |
| [EEGSaver](./eegsaver.md) | Save EEG data (MNE Raw or numpy segments) to disk in multiple formats. |
| [EEGVisualizer](./eegvisualizer.md) | Simple real-time EEG viewer — displays raw MNE Raw data with selectable channels. |
| [EvokedViewer](./evokedviewer.md) | Displays MNE Evoked (ERP) data in butterfly or single-channel mode. |
| [LSL Outlet](./lsl-outlet.md) | LSL Outlet — publish pipeline output as LSL stream (sink node). |
| [MNE Viewer 2D (montage-free)](./mne-viewer-2d-montage-free.md) | MNE Viewer 2D — Montage-Free Plots (markers-ready) |
| [MNEBandpowerViewer](./mnebandpowerviewer.md) | Bar chart of EEG band powers (e.g. theta, alpha, beta), either averaged across channels or per-channel. |
| [PSDVisualizer](./psdvisualizer.md) | Displays Welch PSD curves per channel with optional averaging and dB scaling. |
| [TFRViewer](./tfrviewer.md) | TFRViewer — robuste au changement de fichier / nbre de canaux |

## Preprocessing

| Node | Summary |
|---|---|
| [BCI_EuclideanAlignment](./bci_euclideanalignment.md) | Per-subject Euclidean Alignment for cross-subject BCI. |
| [BCI_Preproc](./bci_preproc.md) | Generic causal preprocessing for EEG: bandpass, notch, CAR, EOG regression, resample, z-score. |
| [MNEAverage](./mneaverage.md) | Compute the mean across epochs to produce an MNE Evoked object. |
| [MNEAverageReference](./mneaveragereference.md) | Apply average re-referencing to EEG channels of a Raw or Epochs object. |
| [MNEBandpassFilter](./mnebandpassfilter.md) | Apply MNE-Python bandpass filtering to an MNE Raw object. Supports high-pass, low-pass, and FIR phase options. |
| [MNEICA](./mneica.md) | ICA decomposition with automatic EOG/ECG artifact detection and removal on Raw or Epochs. |
| [MNENotchFilter](./mnenotchfilter.md) | Apply FIR notch filtering to remove powerline noise (50/60 Hz) and optional harmonics from Raw or Epochs. |
| [MNEResample](./mneresample.md) | Resample an MNE Raw or Epochs object to a target sampling frequency. |

## Processing Nodes

| Node | Summary |
|---|---|
| [BandpowerExt](./bandpowerext.md) | Extract band power features by delegating to an external bandpower script via subprocess. |
| [BandpowerExt_param](./bandpowerext_param.md) | Extract per-channel band power features using a built-in Welch-like estimator (no SciPy required). |
| [BandpowerFeatures](./bandpowerfeatures.md) | Extract per-band power features from EEG segments using Welch PSD estimation. |
| [EEGChannelRMS](./eegchannelrms.md) | Compute per-channel RMS (Root Mean Square) values from an EEG segment or MNE Raw object. |
| [EEGFilterStateful](./eegfilterstateful.md) | Stateful IIR bandpass filter for streaming EEG chunks. |
| [EEGRawFilter](./eegrawfilter.md) | Temporal filtering (HP/LP/BP/Notch) for MNE Raw objects, with async background thread. |
| [EEGSliceFilter](./eegslicefilter.md) | Streaming windowed filter (HP/LP/Notch) with persistent state (FIR or IIR). |
| [RawWindowSlicer](./rawwindowslicer.md) | Slices a continuous MNE Raw into overlapping windows via a QTimer. |

## Segmentation

| Node | Summary |
|---|---|
| [BCI_Epoch](./bci_epoch.md) | Extract fixed-length epochs from continuous EEG: sliding window or event-locked mode. |
| [MNEBaseline](./mnebaseline.md) | Apply a time-baseline correction to mne.Epochs via apply_baseline(). |
| [MNEEpochs](./mneepochs.md) | Create mne.Epochs from an MNE Raw object plus events (explicit or auto-extracted from annotations). |
| [MNEEpochsLite](./mneepochslite.md) | Minimal, robust epoching with automatic event detection (annotations → STIM → fixed-length → manual fallback). |
| [MNEEpochsToSegments](./mneepochstosegments.md) | Stream mne.Epochs one-by-one as segment arrays at a configurable frame rate, for live display. |

## Time-Frequency

| Node | Summary |
|---|---|
| [TFR (Morlet)](./tfr-morlet.md) | Compute time-frequency representation (TFR) using Morlet wavelets on mne.Epochs, with safe auto-clipping of cycles. |

## Transform Nodes

| Node | Summary |
|---|---|
| [MNE Compute SSP Projs](./mne-compute-ssp-projs.md) | Compute SSP projectors for EOG/ECG artifact rejection on MNE Raw objects. |
| [MNE Set Montage](./mne-set-montage.md) | Apply a standard electrode montage to an MNE Raw object with tolerant channel name matching. |

## Visualization

| Node | Summary |
|---|---|
| [PSDTopoViewer](./psdtopoviewer.md) | Topomap or bar-chart of average PSD power in a configurable frequency band. |

## Web Nodes

| Node | Summary |
|---|---|
| [ServerHttpLauncher](./serverhttplauncher.md) | Embedded HTTP server that serves a static directory and receives POST /feedback from a web client. |
| [WebFeedbackClient](./webfeedbackclient.md) | HTTP client that POSTs feedback (label, confidence, payload) to a ServerHttpLauncher /feedback endpoint. |

