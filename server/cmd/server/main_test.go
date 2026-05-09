package main

import (
	"database/sql"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/rs/zerolog"
	_ "modernc.org/sqlite"
)

func TestPackageCompilesUnderGoTest(t *testing.T) {
	// Compiles under go test only; behavioral coverage in task 02+.
}

func TestParseZerologLevel(t *testing.T) {
	l, err := parseZerologLevel("info")
	if err != nil || l != zerolog.InfoLevel {
		t.Fatalf("info: got %v %v", l, err)
	}
	l, err = parseZerologLevel("  INFO  ")
	if err != nil || l != zerolog.InfoLevel {
		t.Fatalf("trim/case: got %v %v", l, err)
	}
	l, err = parseZerologLevel("debug")
	if err != nil || l != zerolog.DebugLevel {
		t.Fatalf("debug: got %v %v", l, err)
	}
	_, err = parseZerologLevel("not-a-level")
	if err == nil {
		t.Fatal("expected error for invalid level")
	}
}

func TestLogFormatHumanReadable(t *testing.T) {
	if !logFormatHumanReadable("console") || !logFormatHumanReadable("") {
		t.Fatal("console and default should be human-readable")
	}
	if logFormatHumanReadable("json") || logFormatHumanReadable("  JSON  ") {
		t.Fatal("json should not use console writer")
	}
	if !logFormatHumanReadable("  CONSOLE  ") {
		t.Fatal("non-json values should be human-readable")
	}
}

func TestGetenvDefault(t *testing.T) {
	key := "MITM_SERVER_GETENV_TEST_" + t.Name()
	t.Setenv(key, "")
	if getenvDefault(key, "fallback") != "fallback" {
		t.Fatal("empty env should use default")
	}
	t.Setenv(key, "override")
	if getenvDefault(key, "fallback") != "override" {
		t.Fatal("set env should win")
	}
}

// If shutdownTimeout changes, update README graceful shutdown section accordingly.
func TestShutdownTimeoutIsTenSeconds(t *testing.T) {
	if shutdownTimeout != 10*time.Second {
		t.Fatalf("shutdownTimeout = %v, update README if this changes", shutdownTimeout)
	}
}

func TestEffectiveSQLiteDSN(t *testing.T) {
	c := config{SQLiteDSN: "file:explicit.db"}
	if c.effectiveSQLiteDSN() != "file:explicit.db" {
		t.Fatalf("DSN override: %q", c.effectiveSQLiteDSN())
	}
	c = config{SQLitePath: "data/app.db"}
	want := sqliteFileDSN("data/app.db")
	if g := c.effectiveSQLiteDSN(); g != want {
		t.Fatalf("path build: got %q want %q", g, want)
	}
}

func TestSqliteFileDSNEncodesAwkwardPath(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "dir with spaces", "name?q&x.db")
	dsn := sqliteFileDSN(dbPath)

	u, err := url.Parse(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if u.Scheme != "file" {
		t.Fatalf("scheme: %q", u.Scheme)
	}
	if u.RawQuery != "_pragma=busy_timeout(5000)&_pragma=foreign_keys(ON)" {
		t.Fatalf("query: %q", u.RawQuery)
	}
	if !strings.Contains(dsn, "%3F") || !strings.Contains(dsn, "%26") || !strings.Contains(dsn, "%20") {
		t.Fatalf("DSN should encode ?, &, and spaces: %q", dsn)
	}
	wantBase := filepath.Base(dbPath)
	if filepath.Base(u.Path) != wantBase {
		t.Fatalf("decoded basename got %q want %q (full path %q)", filepath.Base(u.Path), wantBase, u.Path)
	}
	if !strings.Contains(u.Path, "dir with spaces") {
		t.Fatalf("decoded path should preserve dir segment: %q", u.Path)
	}
}

func TestSqliteFileDSNAwkwardPathOpens(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "dir with spaces", "name?q&x.db")
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		t.Fatal(err)
	}
	dsn := sqliteFileDSN(dbPath)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	if err := db.Ping(); err != nil {
		t.Fatal(err)
	}
}
