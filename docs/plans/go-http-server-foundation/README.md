# Go HTTP server foundation (`server/`)

## Context

The repository already has a **partial skeleton** under [`server/`](../../../server/):

- **Module:** `github.com/purpletooth/mitm_scripts/server`, **Go 1.22** ([`server/go.mod`](../../../server/go.mod)).
- **Layout:** `cmd/server/`, `internal/domain/`, `internal/usecase/`, `internal/ports/`, `internal/adapters/http/` (package `httpadapter`), `internal/adapters/sqlite/`, `internal/platform/log/` — each has `doc.go` and `doc_test.go` (compile-only smoke tests).
- **Composition root:** [`cmd/server/main.go`](../../../server/cmd/server/main.go) is intentionally empty (wiring deferred).
- **Local ignores:** [`server/.gitignore`](../../../server/.gitignore) ignores `*.db`.

Work **extends and fills** this skeleton; do not remove the clean-architecture package boundaries unless a later review agrees on a rename (e.g. `httpadapter` is already established).

**Goal for this initiative:** a **foundation** only — HTTP server startup, SQLite with embedded migrations, colorful dev logging, and minimal endpoints (**health**, **ping**, and **readiness** tied to DB/migrations) to prove wiring. No product API, auth, or extra databases.

## Approach

**Sequence (dependency order, PR-sized):**

1. **Module, layout, domain, and ports** — Lock module path, ensure `go mod tidy` / dependencies strategy, add minimal **domain** types/errors and **port** interfaces that SQLite and HTTP will implement/call. Establishes contracts before adapters.
2. **Platform logging** — `internal/platform/log`: shared **zerolog** + **ConsoleWriter** (colored, pretty console) suitable for local dev; no business logic.
3. **SQLite + migrations** — `internal/adapters/sqlite`: open DB (prefer **pure Go** driver e.g. `modernc.org/sqlite` to avoid CGO in CI unless the team opts in), **`embed.FS`** SQL migrations, **[goose](https://github.com/pressly/goose)** up on startup (or documented single path), implement port(s) from step 1.
4. **Use case + HTTP adapter** — `internal/usecase`: e.g. readiness checks using ports; `internal/adapters/http`: **[chi](https://github.com/go-chi/chi/v5)** router, **`GET /health`**, **`GET /ping`**, **`GET /ready`** (503 when DB/migrations not OK). Handlers delegate to use cases, not raw DB handles.
5. **`cmd` composition root** — `main.go`: config (env/flags), logger, migrate+open SQLite, construct use cases + router, **`http.Server`** with graceful shutdown (**`SIGINT`/`SIGTERM`**).

**Why this order:** contracts (01) before implementations (03–04); logging (02) early so later packages share one setup; SQLite (03) before handlers that expose readiness (04); **`main`** last (05) avoids circular imports and keeps dependency direction inward.

**Parallelization:** 02 can start after 01 once import paths are stable; 03 strictly depends on 01’s ports; 04 depends on 01–03; 05 depends on all.

## Risks and unknowns

| Risk | Mitigation |
|------|------------|
| **SQLite driver (CGO vs pure Go)** | Default **modernc.org/sqlite** in plan; switch to mattn/sqlite3 only if required—document build tags / CI implications. |
| **Migration tooling** | Goose + `embed.FS` is assumed; golang-migrate is acceptable if the implementer aligns subtask 03 and README consistently. |
| **Scope creep** | “Foundation only” — reject extra REST resources in PRs unless needed to test wiring. |
| **`doc_test` / empty `main`** | Replace smoke tests with real tests as code lands; keep `go test ./...` green from `server/`. |

## Definition of done

- `cd server && go test ./...` passes.
- `go run ./cmd/server` listens on a **configurable** address (e.g. `:8080` or `HTTP_ADDR`).
- Stdout logs are **structured**, **leveled**, and **colorized** for dev (zerolog console).
- SQLite opens per config; migrations apply on boot (or one clearly documented code path).
- **`GET /health`** returns **200** without requiring DB.
- **`GET /ping`** returns **200** (minimal liveness; may mirror health for this milestone).
- **`GET /ready`** returns **200** when DB + migration state are OK; **503** otherwise.
- [`server/README.md`](../../../server/README.md) updated with run instructions and main env vars.

## Tasks

1. [Module layout, domain, and ports](./01-module-layout-domain-and-ports.md)
2. [Platform colored logging (zerolog)](./02-platform-colored-logging.md)
3. [SQLite adapter and embedded migrations](./03-sqlite-adapter-and-migrations.md)
4. [Use cases and HTTP adapter (health, ping, ready)](./04-usecase-and-http-adapter.md)
5. [Cmd wiring, config, and graceful shutdown](./05-cmd-wiring-and-shutdown.md)
