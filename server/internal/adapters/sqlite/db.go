package sqlite

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"strings"
	"sync"

	"github.com/pressly/goose/v3"
	"github.com/purpletooth/mitm_scripts/server/internal/domain"
	"github.com/purpletooth/mitm_scripts/server/internal/ports"
	"github.com/rs/zerolog"
)

//go:embed migrations/*.sql
var defaultMigrations embed.FS

// gooseGlobalMu serializes goose package-level state (dialect, BaseFS) and
// migration operations so multiple Store instances do not race.
var gooseGlobalMu sync.Mutex

const (
	// DefaultMigrationsDir is the path within defaultMigrations where goose SQL files live.
	DefaultMigrationsDir = "migrations"
)

// Store implements ports.DatabasePinger, ports.MigrationRunner, and
// ports.MigrationHeadVerifier for SQLite using modernc.org/sqlite and goose v3.
type Store struct {
	db    *sql.DB
	log   zerolog.Logger
	relFS fs.FS // directory containing *.sql (BaseFS root for goose)
}

var (
	_ ports.DatabasePinger        = (*Store)(nil)
	_ ports.MigrationRunner       = (*Store)(nil)
	_ ports.MigrationHeadVerifier = (*Store)(nil)
)

// DefaultMigrationsFS returns the embedded migration files shipped with this package.
func DefaultMigrationsFS() embed.FS {
	return defaultMigrations
}

// NewStore wires a SQLite *sql.DB to goose migrations under migrationsDir within fsys
// (for example fsys = DefaultMigrationsFS() and migrationsDir = DefaultMigrationsDir).
//
// Open the database with driver name "sqlite" after blank-importing modernc.org/sqlite.
//
// DSN examples (modernc.org/sqlite):
//   - "file:path/to/app.db?_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
//   - "file:memdb1?mode=memory&cache=shared" — shared in-memory; use db.SetMaxOpenConns(1) for migrations
//
// The busy_timeout pragma avoids SQLITE_BUSY flakes when multiple connections contend.
func NewStore(db *sql.DB, log zerolog.Logger, fsys fs.FS, migrationsDir string) (*Store, error) {
	sub, err := fs.Sub(fsys, migrationsDir)
	if err != nil {
		return nil, fmt.Errorf("sqlite migrations sub fs: %w", err)
	}
	gooseGlobalMu.Lock()
	defer gooseGlobalMu.Unlock()
	if err := goose.SetDialect("sqlite3"); err != nil {
		return nil, fmt.Errorf("goose sqlite dialect: %w", err)
	}
	return &Store{db: db, log: log, relFS: sub}, nil
}

// Ping implements [ports.DatabasePinger].
func (s *Store) Ping(ctx context.Context) error {
	if err := s.db.PingContext(ctx); err != nil {
		return fmt.Errorf("%w: %w", domain.ErrDatabaseUnavailable, err)
	}
	return nil
}

// RunMigrations implements [ports.MigrationRunner].
func (s *Store) RunMigrations(ctx context.Context) error {
	s.log.Info().Msg("sqlite: applying migrations")
	if _, err := s.embeddedHeadVersion(); err != nil {
		return err
	}
	err := s.withGooseFS(func() error {
		return goose.UpContext(ctx, s.db, ".")
	})
	if err != nil {
		s.log.Error().Err(err).Msg("sqlite: migration run failed")
		return mapMigrationRunError(err)
	}
	s.log.Info().Msg("sqlite: migrations applied")
	return nil
}

// VerifyMigrationsAtHead implements [ports.MigrationHeadVerifier].
// It never creates the goose version table and never runs UP migrations.
func (s *Store) VerifyMigrationsAtHead(ctx context.Context) error {
	head, err := s.embeddedHeadVersion()
	if err != nil {
		return err
	}
	current, found, err := readAppliedVersion(ctx, s.db, goose.TableName())
	if err != nil {
		return fmt.Errorf("%w: %w", domain.ErrDatabaseUnavailable, err)
	}
	if !found || current < head {
		return domain.ErrMigrationsNotAtHead
	}
	if current > head {
		return fmt.Errorf("%w (db version %d, embedded head %d)",
			domain.ErrMigrationsNotAtHead, current, head)
	}
	return nil
}

func mapMigrationRunError(err error) error {
	if err == nil {
		return nil
	}
	for e := err; e != nil; e = errors.Unwrap(e) {
		if errors.Is(e, driver.ErrBadConn) || errors.Is(e, sql.ErrConnDone) {
			return fmt.Errorf("%w: %w", domain.ErrDatabaseUnavailable, err)
		}
		// modernc/sqlite closed pool often returns fmt-wrapped "sql: database is closed"
		// without participating in ErrBadConn in the unwrap chain.
		if strings.Contains(e.Error(), "database is closed") {
			return fmt.Errorf("%w: %w", domain.ErrDatabaseUnavailable, err)
		}
	}
	return err
}

func (s *Store) withGooseFS(fn func() error) error {
	gooseGlobalMu.Lock()
	defer gooseGlobalMu.Unlock()
	goose.SetBaseFS(s.relFS)
	defer goose.SetBaseFS(nil)
	return fn()
}

func (s *Store) embeddedHeadVersion() (int64, error) {
	var v int64
	err := s.withGooseFS(func() error {
		migs, err := goose.CollectMigrations(".", 0, math.MaxInt64)
		if err != nil {
			if errors.Is(err, goose.ErrNoMigrationFiles) {
				return domain.ErrEmbeddedMigrationsMissing
			}
			return err
		}
		if len(migs) == 0 {
			return domain.ErrEmbeddedMigrationsMissing
		}
		v = migs[len(migs)-1].Version
		return nil
	})
	return v, err
}

func readAppliedVersion(ctx context.Context, db *sql.DB, table string) (version int64, tableFound bool, err error) {
	var n int
	if err := db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?`,
		table,
	).Scan(&n); err != nil {
		return 0, false, err
	}
	if n == 0 {
		return 0, false, nil
	}

	rows, err := db.QueryContext(ctx,
		fmt.Sprintf(`SELECT version_id, is_applied FROM %s ORDER BY id DESC`, table))
	if err != nil {
		return 0, true, err
	}
	defer rows.Close()

	skip := make(map[int64]struct{})
	for rows.Next() {
		var vid int64
		var applied int
		if err := rows.Scan(&vid, &applied); err != nil {
			return 0, true, err
		}
		if _, dup := skip[vid]; dup {
			continue
		}
		if applied != 0 {
			return vid, true, nil
		}
		skip[vid] = struct{}{}
	}
	if err := rows.Err(); err != nil {
		return 0, true, err
	}
	return 0, true, nil
}
