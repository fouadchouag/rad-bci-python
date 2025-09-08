# Nodes Catalog

> Auto-generated from plugin `help` dicts. Use Shift+F1 on a node to open its page.

## Analysis

| Node | Summary |
|---|---|
| [PSDWelch](./psdwelch.md) | PSDWelchPlugin |

## BCI/Control

| Node | Summary |
|---|---|
| [BCI_CommandRouter](./bci_commandrouter.md) | Transforme les prédictions en commandes stables (LEFT/RIGHT/UP/DOWN/STOP) |

## BCI/Feedback

| Node | Summary |
|---|---|
| [BCI_BallController](./bci_ballcontroller.md) | Contrôle une balle 2D à partir de pred_idx / proba. |

## BCI/ML

| Node | Summary |
|---|---|
| [BCI_Features](./bci_features.md) | Processing step for EEG streams. |
| [BCI_Predictor](./bci_predictor.md) | Prédicteur en ligne pour BCI. |
| [BCI_Trainer](./bci_trainer.md) | Entraîne un modèle scikit-learn en THREAD (non-bloquant UI) et publie un rapport complet. |

## BCI/Preproc

| Node | Summary |
|---|---|
| [BCI_Preproc](./bci_preproc.md) | Pré-traitement générique (causal) pour EEG: |

## BCI/Segmentation

| Node | Summary |
|---|---|
| [BCI_Epoch](./bci_epoch.md) | Processing step for EEG streams. |

## BCI/Utils

| Node | Summary |
|---|---|
| [BCI_Config](./bci_config.md) | Config manager « no-code » : |
| [BCI_MetricsViewer](./bci_metricsviewer.md) | Affiche les métriques d'un modèle entraîné (venant de BCI_Trainer.report). |
| [BCI_OnlineMetrics](./bci_onlinemetrics.md) | Métriques en ligne (rolling): |
| [BCICollector](./bcicollector.md) | Utility/orchestration node for routing, collection or metrics. |
| [MarkersToClassIdx](./markerstoclassidx.md) | Convertit des marqueurs LSL (strings) en y_idx (int) et y_name (str). |
| [OnlineMetrics](./onlinemetrics.md) | Compare en ligne pred_idx vs y_idx et calcule: |

## Custom

| Node | Summary |
|---|---|
| [RawFilter_C](./rawfilter_c.md) | RawFilter_C: custom node. |

## Features

| Node | Summary |
|---|---|
| [PSDBandFeaturesLite](./psdbandfeatureslite.md) | PSDBandFeaturesLite |

## Input Nodes

| Node | Summary |
|---|---|
| [AcquisitionManager](./acquisitionmanager.md) | AcquisitionManager (léger) — LSL \| Emulator \| Native (disabled) |
| [Array → MNE Raw](./array-mne-raw.md) | Array → MNE Raw (Adapter) — fixed v2 |
| [EEGMatReader](./eegmatreader.md) | EEGMatReader — lecteur .mat (BBCI / BCI Competition / génériques) |
| [EEGReader](./eegreader.md) | Read EEG files/datasets with MNE-Python; emits Raw or window windows. |
| [EEGUniversalReader](./eeguniversalreader.md) | EEGUniversalReader — ultra-fast, tous formats MNE, avec métriques enrichies: |
| [GDFReader](./gdfreader.md) | Read EEG files/datasets with MNE-Python; emits Raw or window windows. |
| [LSL Inlet](./lsl-inlet.md) | LSL Inlet — compatible LiveDisplay / SliceFilter |
| [LSL_EEG_Inlet](./lsl_eeg_inlet.md) | Inlet LSL générique pour flux EEG (float32, multi-canaux). |
| [LSL_EEG_Inlet_Fast](./lsl_eeg_inlet_fast.md) | Inlet EEG non-bloquant : |
| [LSL_Markers_Inlet](./lsl_markers_inlet.md) | Inlet LSL pour flux de marqueurs (strings). |
| [MAT → MNE Raw](./mat-mne-raw.md) | MAT → MNE Raw (BNCI/BCI-Compatible Loader) |
| [MNESampleLoader](./mnesampleloader.md) | MNESampleLoader — charge le dataset d'exemple MNE (sample_audvis_raw.fif) |
| [SyntheticLR](./syntheticlr.md) | Génère un Raw MNE synthétique avec blocs alternés 'Left' / 'Right'. |

## ML

| Node | Summary |
|---|---|
| [ClassifierMetrics](./classifiermetrics.md) | Évalue un dataset publié par EEGClassifier (X/y) via CV. |
| [ClassifierMetrics_1](./classifiermetrics_1.md) | Évalue un dataset {X,y,y_names} (multi-classe) par CV. |
| [EEGClassifier](./eegclassifier.md) | Classification 2 classes (Left/Right) simplifiée. |
| [EEGClassifier_1](./eegclassifier_1.md) | Classif EEG multi-classe avec enregistrement par classe puis entraînement. |
| [EEGClassifier_2](./eegclassifier_2.md) | BCI trainer compact : collecte multi-classe, CV, entraînement et prédiction. |

## ML / Classifier

| Node | Summary |
|---|---|
| [ClassifierRuntime](./classifierruntime.md) | Apply a trained model or compute predictions/probabilities. |

## ML / Features

| Node | Summary |
|---|---|
| [BandpowerFeatures](./bandpowerfeatures.md) | BandpowerFeatures — extrait des features de puissance par bande (Welch). |
| [CSPTrainer](./csptrainer.md) | Train a machine-learning model for BCI. |

## ML / Riemann

| Node | Summary |
|---|---|
| [RiemannCov](./riemanncov.md) | RiemannCov — calcule la covariance SPD d'un segment EEG. |
| [RiemannTSApply](./riemanntsapply.md) | RiemannTSApply — applique la Tangent Space pour obtenir des features 1D. |
| [RiemannTSTrainer](./riemanntstrainer.md) | RiemannTSTrainer — apprend la Tangent Space (pyRiemann). |

## Output Nodes

| Node | Summary |
|---|---|
| [BallFeedback](./ballfeedback.md) | Déplace une balle à gauche/droite selon la prédiction du classifieur. |
| [BandpowerInspector](./bandpowerinspector.md) | Inspecteur bandpower avec: |
| [EEGSaver](./eegsaver.md) | EEGSaver — sauvegarde EEG (Raw MNE ou segment numpy) en plusieurs formats. |
| [EEGVisualizer](./eegvisualizer.md) | Visualize signals, features or predictions. |
| [EvokedViewer](./evokedviewer.md) | EvokedViewer (single-channel capable) |
| [MNE Viewer 2D (montage-free)](./mne-viewer-2d-montage-free.md) | MNE Viewer 2D — Montage-Free Plots (markers-ready) |
| [MNEBandpowerViewer](./mnebandpowerviewer.md) | BandpowerViewer |
| [PSDVisualizer](./psdvisualizer.md) | PSDVisualizer |
| [TFRViewer](./tfrviewer.md) | TFRViewer — robuste au changement de fichier / nbre de canaux |

## Preprocessing

| Node | Summary |
|---|---|
| [MNEAverageReference](./mneaveragereference.md) | MNEAverageReference |
| [MNEBandpassFilter](./mnebandpassfilter.md) | MNEBandpassFilterPlugin (final) |
| [MNEICA](./mneica.md) | MNEICAPlugin (anti-freeze, pins réduits) |
| [MNENotchFilter](./mnenotchfilter.md) | MNENotchFilterPlugin (final) |
| [MNEResample](./mneresample.md) | MNEResamplePlugin (final) |

## Processing

| Node | Summary |
|---|---|
| [EEGChannelRMS](./eegchannelrms.md) | EEGChannelRMSPlugin — Convert Raw/segment to per-channel scalar values (RMS) |

## Processing Nodes

| Node | Summary |
|---|---|
| [BandpowerExt](./bandpowerext.md) | Entrées acceptées: |
| [BandpowerExt_param](./bandpowerext_param.md) | BandpowerExt — extrait des puissances de bandes par canal depuis des segments. |
| [EEGFilterStateful](./eegfilterstateful.md) | EEGFilterStateful — bandpass IIR à état (streaming) |
| [EEGRawFilter](./eegrawfilter.md) | Temporal filtering (HP/LP/BP/Notch) for Raw or windowed data. |
| [EEGSliceFilter](./eegslicefilter.md) | EEGSliceFilter : filtrage streaming (HP/LP/Notch) par fenêtres avec état persistant |
| [RawWindowSlicer](./rawwindowslicer.md) | Windowing/epoching: cut continuous data into segments/epochs. |

## Segmentation

| Node | Summary |
|---|---|
| [MNEEpochs](./mneepochs.md) | MNEEpochs |
| [MNEEpochsLite](./mneepochslite.md) | MNEEpochsLite — Epoching minimal & robuste |
| [MNEEpochsToSegments](./mneepochstosegments.md) | MNEEpochsToSegments |

## Segmentation / Baseline

| Node | Summary |
|---|---|
| [MNEBaseline](./mnebaseline.md) | MNEBaselinePlugin |

## Segmentation/ERP

| Node | Summary |
|---|---|
| [MNEAverage](./mneaverage.md) | MNEAveragePlugin |

## Time-Frequency

| Node | Summary |
|---|---|
| [TFR (Morlet)](./tfr-morlet.md) | MNETFRMorletPlugin (safe v3) |

## Transform Nodes

| Node | Summary |
|---|---|
| [MNE Compute SSP Projs](./mne-compute-ssp-projs.md) | MNE Compute SSP Projs — rapide (EOG / ECG) |
| [MNE Set Montage](./mne-set-montage.md) | MNE Set Montage (robuste) |

## Visualization

| Node | Summary |
|---|---|
| [PSDTopoViewer](./psdtopoviewer.md) | PSDTopoViewer (lite + fullscreen) |

