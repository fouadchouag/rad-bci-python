Nodes Catalog (Excerpt)
Category	Node	Purpose	Inputs	Outputs
Input	EEGUniversalReader	Load EDF/BDF/GDF via MNE	—	raw, segment, ch_names, sfreq, info, events
Processing	EEGFilter	HP/LP/Notch filtering	raw or segment	raw or segment
Output	EEGVisualizer	Scrolling EEG display	raw or segment	—
I/O	LSLInlet	Live EEG stream	—	segment
Utils	SignalLogger	CSV logging	any	—
Polyglot	PolyglotPlugin	External step via JSON I/O	any	any

Each node exposes a help dictionary used by the Quick Help popover.