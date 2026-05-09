package usecase

import (
	"context"

	"github.com/purpletooth/mitm_scripts/server/internal/ports"
)

// Status implements liveness and readiness checks; Health and Ping do not touch ports.
type Status struct {
	pinger   ports.DatabasePinger
	verifier ports.MigrationHeadVerifier
}

// NewStatus builds a Status that uses pinger and verifier for Ready only.
func NewStatus(pinger ports.DatabasePinger, verifier ports.MigrationHeadVerifier) *Status {
	return &Status{
		pinger:   pinger,
		verifier: verifier,
	}
}

// Health reports process-level liveness (no DB).
func (*Status) Health(_ context.Context) error { return nil }

// Ping is a minimal liveness probe (no DB).
func (*Status) Ping(_ context.Context) error { return nil }

// Ready checks database connectivity and that embedded migrations are at head.
func (s *Status) Ready(ctx context.Context) error {
	if err := s.pinger.Ping(ctx); err != nil {
		return err
	}
	return s.verifier.VerifyMigrationsAtHead(ctx)
}
