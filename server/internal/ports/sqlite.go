package ports

import "context"

// Port contracts implemented by internal/adapters/sqlite; interfaces here are DB-agnostic.

// DatabasePinger checks that the database accepts connections (e.g. sql.DB.PingContext).
type DatabasePinger interface {
	Ping(ctx context.Context) error
}

// MigrationRunner applies pending schema migrations (e.g. goose Up on an embed.FS).
type MigrationRunner interface {
	RunMigrations(ctx context.Context) error
}

// MigrationHeadVerifier checks read-only migration state against known migrations
// (e.g. querying goose schema version vs embed.FS revisions). Implementations MUST NOT
// run MigrationRunner.RunMigrations or otherwise apply migrations.
type MigrationHeadVerifier interface {
	VerifyMigrationsAtHead(ctx context.Context) error
}
