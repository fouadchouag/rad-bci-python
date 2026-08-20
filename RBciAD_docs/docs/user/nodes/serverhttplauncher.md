# ServerHttpLauncher

**Category:** Web Nodes

**Language:** Python

**Source:** `server_http_launcher_plugin.py`

## Summary
Embedded HTTP server that serves a static directory and receives POST /feedback from a web client.

## Inputs
| Name | Description |
|---|---|
| host | str — bind address (default "127.0.0.1") |
| port | int — port number (default 8000) |
| workdir | str — directory to serve as static files (must contain index.html) |
| start | bool — True to start the server, False to stop it |

## Outputs
| Name | Description |
|---|---|
| http_url | str or None — full URL of the running server (e.g. "http://127.0.0.1:8000/") |
| is_running | bool — True while the server thread is alive |
| log | str — last log/status message |
| last_feedback | dict or None — most recently received POST /feedback JSON payload |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| host | str | 127.0.0.1 |  | Bind address for the HTTP server. |
| port | int |  |  | Port number for the HTTP server. |
| workdir | str | (cwd) |  | Directory to serve. Must contain index.html for the web UI. |
| start | bool |  |  | Set to True to start, False to stop. |

## Usage
Set the directory containing your web app (index.html), then set start=True or click "Démarrer". Web clients can POST feedback to /feedback and read it back via GET /last.

## Gotchas
- The server runs in a daemon thread — it stops automatically when the process exits.
- Do NOT select a node_modules directory as the served folder.
- GET /last returns the most recent feedback dict as JSON.
- POST /feedback accepts a JSON body; the server replies with {"status":"ok","received":...}.
- CORS is enabled (Access-Control-Allow-Origin: *) for cross-origin web clients.
- If the port is already in use, binding will fail and an error is logged.
- The server object is removed cleanly when the node is deleted (on_remove).

