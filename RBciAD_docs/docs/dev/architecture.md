Architecture


RBciAD couples a Qt‑based node editor with a reactive engine (RxPY) and a plugin system.

flowchart LR
  UI[Qt Scene & Widgets] --> RX[Reactive Engine (RxPY)]
  RX --> N[Nodes]
  N --> C[Connections]
  N --> M[Metrics Logger]
  N --> X[Polyglot Runner]
Lifecycle

__init__ (no heavy work) → setup() (define I/O) → set_input() → execute(in_data, **kwargs) → emit via outputs[...] .on_next(value).

Deterministic Execution

Nodes should be idempotent and free of blocking I/O; long tasks use worker threads or native bindings.