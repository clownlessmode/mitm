# server

Go module for the MITM scripts HTTP service foundation (`github.com/purpletooth/mitm_scripts/server`).

## Run

From **`server/`**:

```bash
go run ./cmd/server
```

The process listens on **`HTTP_ADDR`** (default `:8080`). Stop with **Ctrl+C** (SIGINT) or **SIGTERM**; shutdown allows in-flight requests up to **10 seconds** before exit.

## Configuration

Configuration is read from **environment variables** and can be overridden with **flags** (flags apply after env defaults).

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_ADDR` | `:8080` | Listen address (`host:port`). Flag: `-http-addr` |
| `SQLITE_DSN` | _(empty)_ | Full [modernc.org/sqlite](https://pkg.go.dev/modernc.org/sqlite) DSN. When set, **`SQLITE_PATH` is ignored**. Flag: `-sqlite-dsn` |
| `SQLITE_PATH` | `app.db` | Host path for the DB file when `SQLITE_DSN` is unset. Resolved to an absolute path, then built as `file:///` + URL path–encoded segments + `?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)` (same shape as `sqliteFileDSN` in `cmd/server`). Flag: `-sqlite-path` |
| `LOG_LEVEL` | `info` | Zerolog level: `trace`, `debug`, `info`, `warn`, `error`, `fatal`, `disabled`. Flag: `-log-level` |
| `LOG_FORMAT` | `console` | `console` (human-readable, colored on TTY) or `json` (compact JSON). Flag: `-log-format` |

Example:

```bash
HTTP_ADDR=:3000 LOG_LEVEL=debug LOG_FORMAT=json SQLITE_PATH=./data/app.db go run ./cmd/server
```

### Simulating `/ready` failures

- **`GET /health`** and **`GET /ping`** do not use the database and should return **200** while the process is up.
- **`GET /ready`** returns **200** when the DB is reachable and embedded migrations match the schema head; otherwise **503**.

To see **503** on `/ready`: point `SQLITE_PATH` at a directory (invalid DB), use a corrupted file, or run with `SQLITE_DSN=file:missing/nope.db?...` depending on driver behavior—e.g. delete the DB file after a successful start (while the server still holds a handle) is subtle; simpler: pass an invalid DSN or remove read access to the file so `Ping` or migration verification fails.

SQLite (driver name `sqlite`): prefer a file DSN with `busy_timeout`, e.g. `file:/path/to/app.db?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)`. For in-memory shared databases use `file:memdb1?mode=memory&cache=shared`; `cmd/server` always applies `db.SetMaxOpenConns(1)` on the pool (for file DBs from `SQLITE_PATH` as well).
