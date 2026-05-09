package ports_test

import (
	"context"

	"github.com/purpletooth/mitm_scripts/server/internal/ports"
)

// Noop fakes document the method sets task 03 adapters must satisfy; assignments
// below fail at compile time if interfaces change.

type noopPinger struct{}

func (*noopPinger) Ping(context.Context) error { return nil }

var _ ports.DatabasePinger = (*noopPinger)(nil)

type noopMigrationRunner struct{}

func (*noopMigrationRunner) RunMigrations(context.Context) error { return nil }

var _ ports.MigrationRunner = (*noopMigrationRunner)(nil)

type noopMigrationHeadVerifier struct{}

func (*noopMigrationHeadVerifier) VerifyMigrationsAtHead(context.Context) error { return nil }

var _ ports.MigrationHeadVerifier = (*noopMigrationHeadVerifier)(nil)
