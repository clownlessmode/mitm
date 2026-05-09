package domain

import (
	"errors"
	"fmt"
	"testing"
)

func TestSentinelErrorsWorkWithErrorsIs(t *testing.T) {
	t.Parallel()
	if !errors.Is(ErrDatabaseUnavailable, ErrDatabaseUnavailable) {
		t.Fatal("ErrDatabaseUnavailable not recognized with errors.Is")
	}
	if !errors.Is(ErrMigrationsNotAtHead, ErrMigrationsNotAtHead) {
		t.Fatal("ErrMigrationsNotAtHead not recognized with errors.Is")
	}
	if !errors.Is(ErrEmbeddedMigrationsMissing, ErrEmbeddedMigrationsMissing) {
		t.Fatal("ErrEmbeddedMigrationsMissing not recognized with errors.Is")
	}
	dbWrapped := fmt.Errorf("ping: %w", ErrDatabaseUnavailable)
	if !errors.Is(dbWrapped, ErrDatabaseUnavailable) {
		t.Fatal("wrapped ErrDatabaseUnavailable not recognized with errors.Is")
	}
	wrapped := fmt.Errorf("context: %w", ErrMigrationsNotAtHead)
	if !errors.Is(wrapped, ErrMigrationsNotAtHead) {
		t.Fatal("wrapped ErrMigrationsNotAtHead not recognized with errors.Is")
	}
	wrappedEmb := fmt.Errorf("embed: %w", ErrEmbeddedMigrationsMissing)
	if !errors.Is(wrappedEmb, ErrEmbeddedMigrationsMissing) {
		t.Fatal("wrapped ErrEmbeddedMigrationsMissing not recognized with errors.Is")
	}
}

func TestSentinelErrorsDistinctUnderErrorsIs(t *testing.T) {
	t.Parallel()
	if errors.Is(ErrDatabaseUnavailable, ErrMigrationsNotAtHead) {
		t.Fatal("ErrDatabaseUnavailable must not compare equal to ErrMigrationsNotAtHead")
	}
	if errors.Is(ErrMigrationsNotAtHead, ErrDatabaseUnavailable) {
		t.Fatal("ErrMigrationsNotAtHead must not compare equal to ErrDatabaseUnavailable")
	}
	if errors.Is(ErrEmbeddedMigrationsMissing, ErrDatabaseUnavailable) || errors.Is(ErrDatabaseUnavailable, ErrEmbeddedMigrationsMissing) {
		t.Fatal("ErrEmbeddedMigrationsMissing must not compare equal to ErrDatabaseUnavailable")
	}
	if errors.Is(ErrEmbeddedMigrationsMissing, ErrMigrationsNotAtHead) || errors.Is(ErrMigrationsNotAtHead, ErrEmbeddedMigrationsMissing) {
		t.Fatal("ErrEmbeddedMigrationsMissing must not compare equal to ErrMigrationsNotAtHead")
	}
	combined := fmt.Errorf("both: %w", fmt.Errorf("inner: %w", ErrMigrationsNotAtHead))
	if errors.Is(combined, ErrDatabaseUnavailable) {
		t.Fatal("nested wrap of ErrMigrationsNotAtHead must not match ErrDatabaseUnavailable")
	}
}
