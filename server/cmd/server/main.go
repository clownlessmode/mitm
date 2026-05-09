package main

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	_ "modernc.org/sqlite"

	httpadapter "github.com/purpletooth/mitm_scripts/server/internal/adapters/http"
	"github.com/purpletooth/mitm_scripts/server/internal/adapters/sqlite"
	plog "github.com/purpletooth/mitm_scripts/server/internal/platform/log"
	"github.com/purpletooth/mitm_scripts/server/internal/usecase"
	"github.com/rs/zerolog"
)

const shutdownTimeout = 10 * time.Second

type config struct {
	HTTPAddr   string
	SQLiteDSN  string // from flag/env when set
	SQLitePath string // used when SQLiteDSN is empty after parse
	LogLevel   string
	LogFormat  string
}

func main() {
	cfg := loadConfig()

	level, err := parseZerologLevel(cfg.LogLevel)
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid LOG_LEVEL: %v\n", err)
		os.Exit(1)
	}

	human := logFormatHumanReadable(cfg.LogFormat)
	log := plog.New(level, human)

	db, err := sql.Open("sqlite", cfg.effectiveSQLiteDSN())
	if err != nil {
		log.Fatal().Err(err).Msg("open sqlite")
	}
	// SQLite is serialized per connection; a single connection avoids locking surprises
	// across goroutines (matches shared-cache / migration guidance for this driver).
	db.SetMaxOpenConns(1)
	defer func() {
		_ = db.Close()
	}()

	store, err := sqlite.NewStore(db, log, sqlite.DefaultMigrationsFS(), sqlite.DefaultMigrationsDir)
	if err != nil {
		log.Fatal().Err(err).Msg("sqlite store")
	}

	ctx := context.Background()
	if err := store.RunMigrations(ctx); err != nil {
		log.Fatal().Err(err).Msg("run migrations")
	}

	statusUC := usecase.NewStatus(store, store)
	handler := httpadapter.NewRouter(httpadapter.Deps{Log: log, Status: statusUC})

	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info().Str("addr", cfg.HTTPAddr).Msg("http listening")
		errCh <- srv.ListenAndServe()
	}()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	select {
	case err := <-errCh:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal().Err(err).Msg("http server")
		}
	case sig := <-sigCh:
		log.Info().Str("signal", sig.String()).Msg("shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		if err := srv.Shutdown(shutdownCtx); err != nil {
			log.Error().Err(err).Msg("graceful shutdown failed")
			os.Exit(1)
		}
		log.Info().Msg("shutdown complete")
	}
}

func loadConfig() config {
	cfg := config{
		HTTPAddr:   getenvDefault("HTTP_ADDR", ":8080"),
		SQLitePath: getenvDefault("SQLITE_PATH", "app.db"),
		LogLevel:   getenvDefault("LOG_LEVEL", "info"),
		LogFormat:  getenvDefault("LOG_FORMAT", "console"),
	}
	cfg.SQLiteDSN = os.Getenv("SQLITE_DSN")

	flag.StringVar(&cfg.HTTPAddr, "http-addr", cfg.HTTPAddr, "HTTP listen address (env HTTP_ADDR)")
	flag.StringVar(&cfg.SQLiteDSN, "sqlite-dsn", cfg.SQLiteDSN, "Full SQLite DSN; overrides path (env SQLITE_DSN)")
	flag.StringVar(&cfg.SQLitePath, "sqlite-path", cfg.SQLitePath, "SQLite file path when DSN empty (env SQLITE_PATH)")
	flag.StringVar(&cfg.LogLevel, "log-level", cfg.LogLevel, "trace|debug|info|warn|error|fatal|disabled (env LOG_LEVEL)")
	flag.StringVar(&cfg.LogFormat, "log-format", cfg.LogFormat, "console|json (env LOG_FORMAT)")
	flag.Parse()

	return cfg
}

func (c config) effectiveSQLiteDSN() string {
	if strings.TrimSpace(c.SQLiteDSN) != "" {
		return c.SQLiteDSN
	}
	return sqliteFileDSN(c.SQLitePath)
}

// sqliteFileDSN builds a modernc.org/sqlite file DSN with busy_timeout and foreign_keys.
// The filesystem path is normalized to an absolute path; each path segment is escaped with
// url.PathEscape so characters such as '?', '&', or spaces cannot corrupt the URI query.
func sqliteFileDSN(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = path
	}
	const q = "_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)"
	return "file://" + sqliteEscapedAbsPath(abs) + "?" + q
}

func sqliteEscapedAbsPath(abs string) string {
	p := filepath.ToSlash(abs)

	if vol := filepath.VolumeName(p); vol != "" {
		rest := strings.TrimPrefix(p, filepath.ToSlash(vol))
		rest = strings.TrimPrefix(rest, "/")
		prefix := "/" + strings.TrimSuffix(vol, ":") + ":"
		return prefix + "/" + sqliteEscapePathSegments(rest)
	}

	if filepath.IsAbs(abs) || strings.HasPrefix(p, "/") {
		rest := strings.TrimPrefix(p, "/")
		return "/" + sqliteEscapePathSegments(rest)
	}

	return sqliteEscapePathSegments(p)
}

func sqliteEscapePathSegments(rest string) string {
	if rest == "" {
		return ""
	}
	segs := strings.Split(rest, "/")
	parts := make([]string, 0, len(segs))
	for _, s := range segs {
		if s == "" {
			continue
		}
		parts = append(parts, sqliteEscapePathSegment(s))
	}
	return strings.Join(parts, "/")
}

// sqliteEscapePathSegment escapes one path segment for use before ?_pragma=....
// url.PathEscape leaves '&' unescaped (RFC 3986); SQLite URIs treat '&' as a query
// separator so we encode it explicitly.
func sqliteEscapePathSegment(s string) string {
	return strings.ReplaceAll(url.PathEscape(s), "&", "%26")
}

func getenvDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func logFormatHumanReadable(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "json":
		return false
	default:
		return true
	}
}

func parseZerologLevel(s string) (zerolog.Level, error) {
	l, err := zerolog.ParseLevel(strings.ToLower(strings.TrimSpace(s)))
	if err != nil {
		return zerolog.DebugLevel, err
	}
	return l, nil
}
