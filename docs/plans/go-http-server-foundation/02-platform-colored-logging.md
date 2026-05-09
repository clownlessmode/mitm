# Platform colored logging (zerolog)

**Parent goal:** [Master plan](./README.md)

**Navigation:** [Previous](./01-module-layout-domain-and-ports.md) · [Master plan](./README.md) · [Next: SQLite adapter](./03-sqlite-adapter-and-migrations.md)

## Objective

Provide **`internal/platform/log`** with a **single construction API** that returns a configured **zerolog** logger using **`ConsoleWriter`** (or equivalent) for **pretty, colorized** console output in development.

## Scope

**In scope**

- Add dependency: **`github.com/rs/zerolog`** (and any minimal companion for console colors if using standard patterns).
- Exported function(s) e.g. `New(level, humanReadable bool) zerolog.Logger` — exact signature up to implementer; document behavior.
- Optional: map **`LOG_LEVEL`** / **`LOG_FORMAT`** from env in **05** only — this task may stay **library-only** (constructor args) if preferred.

**Out of scope**

- File logging, log shipping, OpenTelemetry.
- Wiring from **`main`** (task **05**).

## Background

Package name **`log`** shadows the stdlib in imports; use **aliased imports** in consumers (`plog`, `applog`, etc.) — document in **05** or in package doc comment.

## Implementation notes

1. Add zerolog to **`go.mod`** via `go get`.
2. Use **`zerolog.ConsoleWriter`** with **`Out: os.Stdout`** and suitable **`TimeFormat`** for dev readability.
3. Set **global level** only if the team prefers; otherwise return a **local logger** instance to be passed through **`main`** (cleaner for tests).
4. Add a **small test** that the package builds and optionally that level parsing works (no brittle snapshot of ANSI codes required).

## Acceptance criteria

- `cd server && go test ./...` passes.
- Running a trivial snippet or test logger emits **human-readable** lines with **color** when attached to a TTY (document manual check in PR if CI is non-TTY).
- **`go.mod` / `go.sum`** updated.

## Handoff

Task **05** imports this package to build the root logger passed into HTTP/SQLite construction; tasks **03–04** may accept **`zerolog.Logger`** (or `interface{ ... }`) if the implementer introduces a thin logging port—**not required** for foundation if constructors take `zerolog.Logger` directly.
