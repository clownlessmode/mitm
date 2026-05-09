package log

import (
	"io"
	"os"
	"strings"
	"testing"

	"github.com/rs/zerolog"
)

// captureStdout replaces os.Stdout with a pipe for fn, then returns written bytes.
// Do not use t.Parallel with tests that call this — os.Stdout is process-global.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	p := struct{ r, w *os.File }{r: r, w: w}
	os.Stdout = p.w

	defer func() {
		os.Stdout = old
		if p.w != nil {
			_ = p.w.Close()
		}
		if p.r != nil {
			_ = p.r.Close()
		}
	}()

	fn()

	if err := p.w.Close(); err != nil {
		t.Fatal(err)
	}
	p.w = nil

	var buf strings.Builder
	if _, err := io.Copy(&buf, p.r); err != nil {
		t.Fatal(err)
	}
	if err := p.r.Close(); err != nil {
		t.Fatal(err)
	}
	p.r = nil

	return buf.String()
}

func stripANSI(s string) string {
	// Zerolog may emit CSI color sequences when Out is a TTY; pipe writes are
	// usually plain but strip common sequences so assertions stay stable.
	var b strings.Builder
	b.Grow(len(s))
	i := 0
	for i < len(s) {
		if s[i] == '\x1b' && i+1 < len(s) && s[i+1] == '[' {
			j := i + 2
			for j < len(s) && s[j] != 'm' {
				j++
			}
			if j < len(s) && s[j] == 'm' {
				i = j + 1
				continue
			}
		}
		b.WriteByte(s[i])
		i++
	}
	return b.String()
}

func TestNew_JSONFormatContainsLevelAndMessage(t *testing.T) {
	out := captureStdout(t, func() {
		zl := New(zerolog.DebugLevel, false)
		zl.Info().Msg("ping")
	})
	out = stripANSI(out)
	if !strings.Contains(out, `"level":"info"`) {
		t.Fatalf("expected JSON level info, got %q", out)
	}
	if !strings.Contains(out, `"message":"ping"`) {
		t.Fatalf("expected message ping, got %q", out)
	}
}

func TestNew_humanReadableContainsLevelAndMessage(t *testing.T) {
	out := captureStdout(t, func() {
		zl := New(zerolog.DebugLevel, true)
		zl.Info().Msg("ping")
	})
	out = stripANSI(out)
	if !strings.Contains(out, "INF") || !strings.Contains(out, "ping") {
		t.Fatalf("expected ConsoleWriter line with INF and ping, got %q", out)
	}
}

func TestNew_respectsMinLevel(t *testing.T) {
	out := captureStdout(t, func() {
		zl := New(zerolog.WarnLevel, false)
		zl.Info().Msg("quiet")
	})
	out = stripANSI(out)
	if strings.Contains(out, "quiet") {
		t.Fatalf("info below warn should not log, got %q", out)
	}
}
