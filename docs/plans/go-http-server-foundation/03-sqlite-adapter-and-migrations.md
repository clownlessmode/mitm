# SQLite adapter and embedded migrations

**Parent goal:** [Master plan](./README.md)

**Navigation:** [Previous](./02-platform-colored-logging.md) · [Master plan](./README.md) · [Next: Use case and HTTP](./04-usecase-and-http-adapter.md)

## Objective

Implement **`internal/adapters/sqlite`**: open SQLite, run **embedded** SQL migrations with **goose**, and satisfy **`internal/ports`** interfaces from task **01** so **`GET /ready`** can query health/migration state later.

## Scope

**In scope**

- Dependencies: **`github.com/pressly/goose/v3`**, **`database/sql`**, and a SQLite driver — **default `modernc.org/sqlite`** (pure Go); document if switching to CGO.
- **`embed.FS`** holding migration files under a stable subdirectory (e.g. `migrations/*.sql` with goose headers).
- Type(s) that implement **`ports`** (e.g. open + ping + `goose` up / version check).
- **`go test`** using **`:memory:`** or **temp file** DB: migrations apply, ping succeeds, optional assertion on goose version table.

**Out of scope**

- HTTP handlers, **`main`** wiring.
- Non-SQLite drivers.

## Background

- **`server/.gitignore`** already ignores `*.db` — dev file DB paths are safe for local runs.
- Goose file format: use **`-- +goose Up`** / **`Down`** sections per file; numbering `00001_*.sql` style.

## Implementation notes

1. `go get` goose + modernc sqlite; wire **`sql.Open`** with DSN appropriate for the driver.
2. On **`Open`/`Migrate`**: call **`goose.SetBaseFS`**, **`goose.SetTableName`** if needed, then **`Up`** (or equivalent) from embedded FS.
3. Implement **`01`**’s port(s); return **typed errors** or **domain** errors where **`04`** maps to 503.
4. Log migration events via **`zerolog.Logger`** passed from caller (constructed in **05**) — avoid **`log` global** if possible.
5. Document **DSN** quirks (e.g. `_pragma=busy_timeout(5000)`) in code comment or **`server/README.md`** brief note.

## Acceptance criteria

- `cd server && go test ./...` passes; **`internal/adapters/sqlite`** has at least one test exercising migrations.
- Embedded migration(s) create a minimal table (e.g. `_meta` or app table) to prove ordering.
- No **HTTP** imports from this package.

## Handoff

Task **04** receives concrete **`ports`** implementations from this package; task **05** constructs DSN/path from config and passes logger + DB adapter into use cases and router.
