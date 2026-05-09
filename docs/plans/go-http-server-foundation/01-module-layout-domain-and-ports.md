# Module layout, domain, and ports

**Parent goal:** [Master plan](./README.md)

**Navigation:** · [Master plan](./README.md) · [Next: Platform colored logging](./02-platform-colored-logging.md)

## Objective

Stabilize the existing **`server/`** module structure and introduce **minimal domain** artifacts plus **port interfaces** so later PRs implement adapters without refactoring package boundaries.

## Scope

**In scope**

- Confirm or lightly adjust **`server/go.mod`** (already `github.com/purpletooth/mitm_scripts/server`, Go 1.22); add **no runtime dependencies** unless required for stubs (prefer none — implementations add deps).
- **`internal/domain`:** small exported types/errors as needed for readiness/use cases (e.g. sentinel errors — keep tiny).
- **`internal/ports`:** interfaces for what SQLite must provide (e.g. ping, migration runner, version check — exact names chosen by implementer but documented here in code).
- Keep existing **`doc.go`** / **`doc_test.go`** pattern or migrate them when adding real identifiers (avoid orphaned package-only stubs if they block tests).

**Out of scope**

- Zerolog/SQLite/Chi (later tasks).
- **`main.go`** wiring.

## Background

Skeleton paths (existing):

| Package | Path | Go package name |
|---------|------|----------------|
| Composition | `cmd/server` | `main` |
| Domain | `internal/domain` | `domain` |
| Use cases | `internal/usecase` | `usecase` |
| Ports | `internal/ports` | `ports` |
| HTTP | `internal/adapters/http` | `httpadapter` |
| SQLite | `internal/adapters/sqlite` | `sqlite` |
| Logging | `internal/platform/log` | `log` |

Implementers depend on **`ports`** from adapters and use cases, never the reverse.

## Implementation notes

1. Re-read **`server/go.mod`**; run `cd server && go mod tidy` (should stay minimal).
2. Add **`ports`** interfaces describing DB health / migration completeness—keep them **narrow** (YAGNI) so **`03`** implements them verbatim.
3. Add **`domain`** errors or tiny value objects only where **`04`** avoids stringly-typed status.
4. Optional: **`usecase`** package may remain empty until task **04**, or export a **`HealthResult`-style placeholder type—avoid unused exports that fail lint rules.
5. Do **not** rename `httpadapter` without updating this plan’s README table.

## Acceptance criteria

- `cd server && go test ./...` passes.
- **`internal/ports`** exports at least one interface that **`03`** can implement for DB/migration readiness.
- **`internal/domain`** compiles; no placeholder `var _ = ...` hacks that skip real design.
- No new production code under **`cmd/`** in this PR.

## Handoff

Task **02** expects a stable module path and **no import cycles**; task **03** expects **concrete `ports` method sets** and optional domain errors for **`04`**.
