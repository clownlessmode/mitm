// Package sqlite implements SQLite persistence and goose-based migrations for the server.
//
// Use modernc.org/sqlite (import `_ "modernc.org/sqlite"`) and driver name "sqlite".
// Prefer a DSN with busy_timeout, for example:
//
//	file:/path/to/app.db?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)
package sqlite
