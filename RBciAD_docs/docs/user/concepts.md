Concepts
Flow‑Based Graphs

Pipelines are graphs where nodes transform data and emit outputs; edges carry values to subscribers.

Reactive Engine (RxPY)

Inputs/outputs are BehaviorSubjects. When a node’s set_input() updates, execute() runs and pushes new outputs downstream.

Data Types

raw: mne.io.Raw

segment: 2D float array [n_channels, n_samples]

features: vectors/JSON with metadata

events: stimulus/event markers

Determinism & Idempotence

Given the same input state, execute() should produce the same outputs and avoid side effects.