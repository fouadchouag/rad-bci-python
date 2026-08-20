# WebFeedbackClient

**Category:** Web Nodes

**Language:** Python

**Source:** `web_feedback_client.py`

## Summary
HTTP client that POSTs feedback (label, confidence, payload) to a ServerHttpLauncher /feedback endpoint.

## Inputs
| Name | Description |
|---|---|
| host | str — server host to connect to (default "127.0.0.1") |
| port | int — server port (default 8000) |
| label | str — classification label to send (required for sending) |
| confidence | float or None — optional confidence value (0..1) |
| payload | dict or None — optional extra key-value pairs to merge into the JSON body |

## Outputs
| Name | Description |
|---|---|
| status | str — "sent" on success, "missing_fields" if label/host/port invalid, or "error: ..." on failure |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| host | str | 127.0.0.1 |  | Target server host. |
| port | int |  |  | Target server port. |

## Usage
Connect label (and optionally confidence/payload) from a classifier upstream. Set the host and port of a running ServerHttpLauncher. Each execute() sends a POST /feedback with the current values.

## Gotchas
- Requires the "requests" library (pip install requests). If missing, status returns "error: requests missing".
- The POST body always includes a "ts" (timestamp) field automatically.
- If payload is a dict, its keys are merged with label/ts/confidence (payload keys take precedence only if not already set via setdefault).
- The HTTP timeout is 2 seconds — slow servers will cause a timeout error.
- Only sends when label, host, and port are all non-empty/non-None.
- The "Test" button in the UI sends a label="TEST" message to the configured host:port.

