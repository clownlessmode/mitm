package domain

import "errors"

var (
	// ErrDatabaseUnavailable means the datastore does not accept connections
	// (e.g. Ping failed).
	ErrDatabaseUnavailable = errors.New("database unavailable")

	// ErrMigrationsNotAtHead means the database schema version is behind the
	// latest embedded migration set.
	ErrMigrationsNotAtHead = errors.New("migrations not at head")

	// ErrEmbeddedMigrationsMissing means no migration SQL files were found in the
	// configured filesystem (readiness cannot be verified or applied).
	ErrEmbeddedMigrationsMissing = errors.New("embedded migrations missing or empty")
)
