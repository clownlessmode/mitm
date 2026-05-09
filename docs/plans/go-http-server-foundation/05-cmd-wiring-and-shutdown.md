# Cmd wiring, config, and graceful shutdown

**Parent goal:** [Master plan](./README.md)

**Navigation:** [Previous](./04-usecase-and-http-adapter.md) · [Master plan](./README.md)

## Objective

Implement **`cmd/server/main.go`** as the **composition root**: configuration, logger, SQLite open + migrate, use case + router construction, **`http.Server`** startup, and **graceful shutdown** on signals.

## Scope

**In scope**

- **Config:** environment variables and/or flags for **HTTP listen address**, **SQLite path/DSN**, **log level** (minimum). Use **`flag`** or lightweight env helper — keep stdlib-first.
- **Lifecycle:** `ListenAndServe` in a goroutine; **`signal.Notify`** for **`SIGINT`/`SIGTERM`**; **`Shutdown(ctx)`** with timeout (e.g. 10s).
- **Exit codes:** non-zero on fatal config/DB/migration errors with **logged** reason.
- Update **`server/README.md`** with run example and env vars.
- Extend **`main_test.go`** only if useful (e.g. build tag test); avoid testing full server in unit test unless already fast.

**Out of scope**

- Docker, systemd units, production hardening beyond basics.

## Background

- **[`cmd/server/main.go`](../../../server/cmd/server/main.go)** is currently empty — this task owns it end-to-end.
- Import **`httpadapter`**, **`sqlite`**, **`usecase`**, **`platform/log`**, **`ports`** as needed; **dependency direction** must remain: `main` → adapters/usecase → ports/domain.

## Implementation notes

1. Parse config first; fail fast with **zerolog** (or stderr before logger exists — acceptable bootstrap pattern).
2. Open DB + run migrations using **`03`**’s API; construct use cases + router from **`04`**.
3. Pass **`zerolog.Logger`** through constructors (no global logger unless already chosen in **02**).
4. Document: `go run ./cmd/server` from **`server/`** directory.
5. Manual verification: `curl` **/health**, **/ping**, **/ready** locally.

## Acceptance criteria

- `cd server && go test ./...` passes.
- `cd server && go run ./cmd/server` starts; `curl` to **/health** and **/ping** returns **200**.
- **/ready** returns **200** with valid DB and **503** when DB is broken or missing (document how to simulate).
- Process exits cleanly on **Ctrl+C** (no hung listeners).
- **`server/README.md`** documents configuration.

## Handoff

Foundation complete; future work adds real domain features behind new use cases and routes without restructuring these layers.
