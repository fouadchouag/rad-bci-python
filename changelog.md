# Changelog

All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- 
### Changed
- 
### Fixed
- 

## [1.6.0] - 2025-08-20

### Added
-
### Changed
-
### Fixed
-


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
