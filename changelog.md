# Changelog

All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

# Changelog

## [1.10.0] - 2025-09-10
### Added
- validation lien par famille/ runtime
- zoom in / zoom out
- Export **PNG / PDF / SVG** recadré automatiquement sur la **zone occupée par les nœuds**.
- Raccourci **Ctrl+E** pour l’export multi-format.
- Option **fond transparent** pour PNG (param interne).

### Changed
- Bouton toolbar renommé en **“Export PNG/PDF/SVG”**.
- SVG/PDF: rendu vectoriel propre, désactivation temporaire des **pens cosmétiques** pour garder une épaisseur lisible.

### Fixed
- PDF qui ajoutait des marges → **marges à 0** (`QPdfWriter.setPageMargins`).
- Erreur `name: _temp_vector_tweaks is not defined` supprimée.
- Recadrage PNG : disparition des grands espaces blancs autour du workflow.

<<<<<<< HEAD
### Notes
- Compatibilité runtime des connexions conservée ; logs plus clairs.
- `EEGUniversalReader` : métriques étendues + streaming robuste.
=======
## [1.6.0] - 2025-08-20
>>>>>>> 6abb661dc733b61835fb8ab4cbcc124b2fd9923b


## [1.9.0] - 2025-09-08
### Added
- In-app Help: Shift+F1 opens node page; “?” quick help badges.
- Low-code help autofill (Summary/Usage → injecte `help` dict).
- Nodes Catalog generator (from plugins’ help).

### Fixed
- F1 search bar with Material theme in embedded viewer.
- Version shown in title from core/version.py.

### Changed
- Low-code wrappers: improved Nyquist guard & preview options.


<<<<<<< HEAD
[1.8.0] — 2025-09-01
Added
Metrics CLI: Δ% vs W1, seuils UX (100/200/500/1000 ms, 0.1/1/10 s, 60/30 fps),
TTFP zoom (0–200 ms), multipanel (a…f), camera-ready + caption, --fontscale.
Scripts de reproductibilité: parse_events_min.py, Annex_Repro_Methods.md, README_RBciAD_Metrics.md.
Exports vectoriels: SVG/PDF pour les 6 graphes + multipage PDF.
Changed
Figures avec polices agrandies et repères UX superposés.
Notes
Données & artefacts dans benchmarks/ et figures/ (voir README).


## [1.7.0] - 2025-08-25
### Added
Métriques manuelles via clavier : démarrer/arrêter avec F9 (toggle) ou F10 (stop).
Plus de lancement auto : aucun fichier dans runs/ tant que les métriques ne sont pas déclenchées.
UI clean : bouton “Start TTFP/bench” retiré de EEGLiveDisplay pour éviter la confusion.
Hooks de métriques étendus dans tous les nœuds (Reader → Filter → Display) :
RUN_META, CPU_MEM
FILE_OPEN, FILE_READY, FILE_ERROR, FILE_CLOSED
READ_START, READ_STOP, META_RESET, EVENTS
PARAM_CHANGE
START_TTFP, FIRST_FRAME, FRAME_RENDERED (+ dropped)
FILTER_START, FILTER_DONE, FILTER_FAIL
Analyse offline améliorée :
utils/metrics_eval.py : TTFP, latences PARAM_CHANGE → FRAME, FPS, CPU/RSS (avg/max), compteurs d’événements, durées par filtre (p50/p95), erreurs, etc.
utils/build_tables_from_metrics.py : corrige les dtypes, gère les NaN, ajoute FPS, Dropped (%), Throughput (kS/s), agrégats par groupe de filtre (dur_med_s, dur_p95_s, fail_pct).
🧩 Changements notables
EEGUniversalReader

Ouverture asynchrone “smart preview” (pré-crop auto sur gros fichiers).
Lazy/memmap + fallback preload ; “Turbo GDF” optionnel.
Journalisation détaillée des paramètres d’ouverture (picks, decim, resample…).
EEGSliceFilter

Filtrage étatful (HP/LP/Notch) via scipy.signal en sos.
Hooks FILTER_START/DONE/FAIL + capture des paramètres (hp/lp/order/notch).
Émission de méta uniquement quand ça change (anti-spam).
EEGLiveDisplay

Suppression du bouton bench ; rendu fluide (throttling FPS, décimation).
Ring-buffer segment ; logs FIRST_FRAME, FRAME_RENDERED (avec drop).
Garde-fous UI (arrêt timer, popup cleanup) → moins d’erreurs Qt.
🛠️ Bug fixes
Exceptions Qt (QTimer/QLabel “wrapped C/C++ object … deleted”) atténuées par des gardes et un nettoyage ordonné.
Robustesse des conversions dtype dans la génération des tables de métriques.
⚠️ Breaking / comportement
Les métriques ne démarrent plus automatiquement au lancement de l’app : il faut appuyer sur F9 (ou binder un menu).
Si vous aviez des scripts qui s’attendaient à des logs au démarrage, adaptez-les (hotkey F9).
⬆️ Upgrade notes
Mettez à jour requirements si nécessaire : scipy, mne.
Lancez l’app, démarrez les métriques avec F9, arrêtez avec F9 ou F10.
Analyse :
python utils/metrics_eval.py runs --outdir metrics_results
python utils/build_tables_from_metrics.py metrics_results --outdir out

=======
>>>>>>> 6abb661dc733b61835fb8ab4cbcc124b2fd9923b
## [1.6.0] - 2025-08-19
### Added
- **Logger Dock** intégré à la fenêtre principale (affichable/masquable) avec capture des logs Python et bascule « Afficher les logs » dans la barre d’outils.
- **Sauvegarde/Chargement des paramètres des nœuds** dans les workflows : persistance des configs via `export_config()`/`import_config()` (fallback `config_in`).
- **Z-order UX** : le nœud sélectionné passe automatiquement au premier plan ; les liens restent en fond.
- **BCI_Config** : bouton *Scan workflow*, *Preview*, *Revert*, *Apply (selected/class/all)*, *Save/Load preset* ; recherche nœuds/paramètres ; surlignage des champs modifiés ; hints (min/max/step/enum/help/order).

### Changed
- **EEGLiveDisplay** : lissage des dessins (decimation), ring buffer pour le mode *segment*, limitation FPS, popup « vue agrandie », sélection flexible de canaux, meilleure gestion des métadonnées (fs, noms, long. segment).
- **EEGRawFilter** : filtrage *offline* en tâche de fond (QThread) avec passage immédiat du raw en *preview* puis push du raw filtré, nettoyage robuste du thread, propagation des méta.
- **EEGSliceFilter** : filtrage streaming étatful (SOS IIR) par canal, état réinitialisable, émission des méta uniquement quand elles changent.
- **EEGUniversalReader** : émission de `ch_names` et `sfreq` uniquement lors des *reset*, gestion annotations/événements, resampling optionnel, auto-play segment.

### Fixed
- Crash **BCI_MetricsViewer** sur rapports partiels (None/clé manquante) + rendu HTML robuste de la matrice de confusion.
- **BCI_OnlineMetrics** : maj des métriques en temps réel, robustesse types/indices, rolling window reset.
- **MainWindow** : correction `log_dock` (AttributeError) ; liens de connexions forcés sous les nœuds ; recentrage création/chargement.
- **BCI_Config** : application fiable des presets (sélection, par classe, global), re-build du formulaire après import.

---

## [1.5.0] - 2025-08-18
### Added
- Nouvelle passe de performance « sans GIL apparent » côté UI : gros calculs déportés (thread pour filtrage offline), throttling de rendu, décimation.
- **BCI_MetricsViewer** (CV mean±std, Balanced Acc, F1 macro, confusion, per-class, export JSON/CSV).
- **BCI_OnlineMetrics** (rolling accuracy + confusion cumulée, fenêtre paramétrable).
- Améliorations **EEGLiveDisplay** (modes `raw` & `segment`, horloge monotone, *loop*, popup).
- Templates de workflows (vierge + pipelines de base).

### Changed
- Palette des plugins par catégorie, découverte dynamique.
- Créateur low-code (ajout rapide de nœuds).

### Fixed
- Connexions plus tolérantes via synonymes de pins (raw/data/eeg, sfreq/fs, etc.).

---

## [1.4.0] - 2025-07-30
### Added
- **EEGUniversalReader** (lecteur multi-formats basés MNE, chunks + overlap, *loop*, sélection de types de canaux).
- **EEGSliceFilter** (première version, HP/LP/Notch, état persistant).
- **EEGRawFilter** (première version, FIR/IIR zero-phase).

### Changed
- Améliorations UX de la scène (scroll/zoom, centrage sur nœud créé).

---

## [1.3.0] - 2025-07-10
### Added
- Sauvegarde/chargement de workflows (nœuds + positions + connexions).

### Changed
- Registre de plugins par nom affiché et nom de classe.

---

## [1.2.0] - 2025-06-15
### Added
- Nœuds de base I/O, pipeline minimal d’exemple.

---

## [1.1.0] - 2025-06-01
### Added
- Système de **pins** (entrées/sorties) et connexions visuelles.
- Découverte de plugins (squelette).

---

## [1.0.0] - 2025-05-20
### Added
- Première version publique : canvas de nœuds, scène Qt, base du routeur Rx, structure du projet.
