# Use cases and HTTP adapter (health, ping, ready)

**Parent goal:** [Master plan](./README.md)

**Navigation:** [Previous](./03-sqlite-adapter-and-migrations.md) · [Master plan](./README.md) · [Next: Cmd wiring](./05-cmd-wiring-and-shutdown.md)

## Objective

Add **`internal/usecase`** services that answer **liveness** and **readiness** using **`ports`**, and **`internal/adapters/http`** routes on **chi**: **`GET /health`**, **`GET /ping`**, **`GET /ready`**.

## Scope

**In scope**

- Dependency: **`github.com/go-chi/chi/v5`**.
- **Use case** type(s): e.g. `Health()` (always OK), `Ping()`, `Ready(ctx)` delegating to DB/migration port(s).
- **Router constructor** e.g. `NewRouter(deps) http.Handler` with chi; map status codes: **200** health/ping; **200/503** ready.
- **Tests:** use case tests with **fakes/mocks** for ports; HTTP tests with **`httptest`** for the three routes.

**Out of scope**

- Auth, metrics middleware (optional chi **RequestID** only if trivial).
- **`main`** — task **05**.

## Background

- Package **`httpadapter`** — keep name consistent with existing **`doc.go`**.
- **`/health`**: should **not** require DB (per master plan).
- **`/ping`**: minimal OK response (JSON or plain text — pick one convention and use everywhere for these three).
- **`/ready`**: uses **`ports`** implemented by **`sqlite`** package.

## Implementation notes

1. Define small **`Deps`** struct for router (logger, use cases).
2. Handlers call use cases only; **no** `*sql.DB` in handlers.
3. Standardize **response body** and **Content-Type** across the three endpoints.
4. Ensure **context** passed to **`Ready`** honors cancellation.

## Acceptance criteria

- `cd server && go test ./...` passes.
- **`GET /health`** and **`GET /ping`** return **200** without DB.
- **`GET /ready`** returns **503** when fake port simulates failure; **200** when OK.
- Router is **`http.Handler`**-compatible for **`http.Server`** in **05**.

## Handoff

Task **05** imports **`httpadapter.NewRouter`**, injects real SQLite-backed port implementations, and starts the server.
