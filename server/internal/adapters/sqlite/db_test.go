package sqlite

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"testing/fstest"

	"github.com/purpletooth/mitm_scripts/server/internal/domain"
	"github.com/rs/zerolog"
	_ "modernc.org/sqlite"
)

func TestStore_migrations_apply_and_verify(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "test.db") + "?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(1)

	log := zerolog.Nop()
	store, err := NewStore(db, log, DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		t.Fatal(err)
	}

	if err := store.VerifyMigrationsAtHead(ctx); !errors.Is(err, domain.ErrMigrationsNotAtHead) {
		t.Fatalf("Verify before migrate: got %v want ErrMigrationsNotAtHead", err)
	}

	if err := store.RunMigrations(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.Ping(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.VerifyMigrationsAtHead(ctx); err != nil {
		t.Fatal(err)
	}

	var rows int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM schema_meta`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 0 {
		t.Fatalf("schema_meta row count = %d, want 0 (shipped 00001 only creates table)", rows)
	}
}

// Ordering is enforced by goose parsing migration filenames (numeric version prefixes),
// not by iteration order of MapFS entries.
func TestStore_migrations_apply_ordering_test_fs(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "order.db") + "?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(1)

	orderFS := fstest.MapFS{
		"migrations/00001_init.sql": &fstest.MapFile{
			Mode: 0o644,
			Data: []byte(`-- +goose Up
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

-- +goose Down
DROP TABLE IF EXISTS schema_meta;
`),
		},
		"migrations/00002_ordering_probe.sql": &fstest.MapFile{
			Mode: 0o644,
			Data: []byte(`-- +goose Up
INSERT INTO schema_meta (key, value) VALUES ('ordering_probe', '00002_after_00001');

-- +goose Down
DELETE FROM schema_meta WHERE key = 'ordering_probe';
`),
		},
	}

	store, err := NewStore(db, zerolog.Nop(), orderFS, "migrations")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.RunMigrations(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.VerifyMigrationsAtHead(ctx); err != nil {
		t.Fatal(err)
	}

	var keys int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM schema_meta`).Scan(&keys); err != nil {
		t.Fatal(err)
	}
	if keys != 1 {
		t.Fatalf("schema_meta row count = %d, want 1 (second migration runs after first)", keys)
	}
	var probeVal string
	if err := db.QueryRowContext(ctx,
		`SELECT value FROM schema_meta WHERE key = 'ordering_probe'`,
	).Scan(&probeVal); err != nil {
		t.Fatal(err)
	}
	if probeVal != "00002_after_00001" {
		t.Fatalf("ordering probe value = %q", probeVal)
	}
}

func TestVerify_does_not_create_version_table(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "probe.db") + "?_pragma=busy_timeout(5000)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(1)

	store, err := NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.VerifyMigrationsAtHead(ctx); !errors.Is(err, domain.ErrMigrationsNotAtHead) {
		t.Fatalf("Verify: %v", err)
	}

	var n int
	err = db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?`,
		"goose_db_version",
	).Scan(&n)
	if err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Fatal("Verify must not create goose_db_version")
	}

	var metaTables int
	err = db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_meta'`,
	).Scan(&metaTables)
	if err != nil {
		t.Fatal(err)
	}
	if metaTables != 0 {
		t.Fatal("Verify must not create schema_meta (migrations not run)")
	}
}

func TestStore_empty_embedded_migrations(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	migrationsPath := filepath.Join(dir, "migrations")
	if err := os.MkdirAll(migrationsPath, 0o755); err != nil {
		t.Fatal(err)
	}
	dsn := "file:" + filepath.Join(dir, "empty.db") + "?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(1)

	store, err := NewStore(db, zerolog.Nop(), os.DirFS(dir), "migrations")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.VerifyMigrationsAtHead(ctx); !errors.Is(err, domain.ErrEmbeddedMigrationsMissing) {
		t.Fatalf("Verify: got %v want ErrEmbeddedMigrationsMissing", err)
	}
	if err := store.RunMigrations(ctx); !errors.Is(err, domain.ErrEmbeddedMigrationsMissing) {
		t.Fatalf("RunMigrations: got %v want ErrEmbeddedMigrationsMissing", err)
	}
}

func TestStore_in_memory_ping_and_migrate(t *testing.T) {
	ctx := context.Background()
	db, err := sql.Open("sqlite", "file:memdb2?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	db.SetMaxOpenConns(1)

	store, err := NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.RunMigrations(ctx); err != nil {
		t.Fatal(err)
	}
	if err := store.Ping(ctx); err != nil {
		t.Fatal(err)
	}
}

func TestNewStore_concurrent_no_panic(t *testing.T) {
	base := t.TempDir()
	const n = 16
	var wg sync.WaitGroup
	var mu sync.Mutex
	var firstErr error
	setErr := func(err error) {
		if err == nil {
			return
		}
		mu.Lock()
		if firstErr == nil {
			firstErr = err
		}
		mu.Unlock()
	}
	wg.Add(n)
	for i := 0; i < n; i++ {
		go func(i int) {
			defer wg.Done()
			dir := filepath.Join(base, strconv.Itoa(i))
			if err := os.MkdirAll(dir, 0o755); err != nil {
				setErr(err)
				return
			}
			dsn := "file:" + filepath.Join(dir, "c.db") + "?_pragma=busy_timeout(5000)"
			db, err := sql.Open("sqlite", dsn)
			if err != nil {
				setErr(err)
				return
			}
			defer db.Close()
			db.SetMaxOpenConns(1)
			_, err = NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
			setErr(err)
		}(i)
	}
	wg.Wait()
	if firstErr != nil {
		t.Fatal(firstErr)
	}
}

func TestRunMigrations_closed_db_maps_unavailable(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "closed.db") + "?_pragma=busy_timeout(5000)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	store, err := NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		_ = db.Close()
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if err := store.RunMigrations(ctx); !errors.Is(err, domain.ErrDatabaseUnavailable) {
		t.Fatalf("RunMigrations on closed db: got %v want ErrDatabaseUnavailable", err)
	}
}

func TestPing_closed_db_maps_unavailable(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "ping.db") + "?_pragma=busy_timeout(5000)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	store, err := NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		_ = db.Close()
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if err := store.Ping(ctx); !errors.Is(err, domain.ErrDatabaseUnavailable) {
		t.Fatalf("Ping on closed db: got %v want ErrDatabaseUnavailable", err)
	}
}

func TestVerifyMigrationsAtHead_closed_db_maps_unavailable(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	dsn := "file:" + filepath.Join(dir, "verify_closed.db") + "?_pragma=busy_timeout(5000)"
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	store, err := NewStore(db, zerolog.Nop(), DefaultMigrationsFS(), DefaultMigrationsDir)
	if err != nil {
		_ = db.Close()
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if err := store.VerifyMigrationsAtHead(ctx); !errors.Is(err, domain.ErrDatabaseUnavailable) {
		t.Fatalf("VerifyMigrationsAtHead on closed db: got %v want ErrDatabaseUnavailable", err)
	}
}
