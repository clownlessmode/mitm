package httpadapter

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/purpletooth/mitm_scripts/server/internal/domain"
	"github.com/purpletooth/mitm_scripts/server/internal/usecase"
	"github.com/rs/zerolog"
)

type fakePinger struct {
	err error
}

func (f *fakePinger) Ping(_ context.Context) error { return f.err }

type fakeVerifier struct {
	err error
}

func (f *fakeVerifier) VerifyMigrationsAtHead(_ context.Context) error { return f.err }

// stubLivenessProbe implements StatusProbe; used to assert /health and /ping invoke Health/Ping
// and keep HTTP 200 even when those methods return errors.
type stubLivenessProbe struct {
	healthErr, pingErr       error
	healthCalled, pingCalled bool
}

func (s *stubLivenessProbe) Health(context.Context) error {
	s.healthCalled = true
	return s.healthErr
}

func (s *stubLivenessProbe) Ping(context.Context) error {
	s.pingCalled = true
	return s.pingErr
}

func (*stubLivenessProbe) Ready(context.Context) error { return nil }

func TestRoutes_HealthAndPing(t *testing.T) {
	log := zerolog.Nop()
	s := usecase.NewStatus(&fakePinger{}, &fakeVerifier{})
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: s}))
	t.Cleanup(srv.Close)

	for _, path := range []string{"/health", "/ping"} {
		t.Run(path, func(t *testing.T) {
			res, err := http.Get(srv.URL + path)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != http.StatusOK {
				t.Fatalf("status: %d", res.StatusCode)
			}
			if ct := res.Header.Get("Content-Type"); ct != "application/json" {
				t.Fatalf("Content-Type: %q", ct)
			}
			var body probeResponse
			if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if !body.OK {
				t.Fatalf("body: %+v", body)
			}
		})
	}
}

func TestRoutes_Liveness_OK_OnHealthPingError(t *testing.T) {
	log := zerolog.Nop()
	st := &stubLivenessProbe{healthErr: errors.New("health"), pingErr: errors.New("ping")}
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: st}))
	t.Cleanup(srv.Close)

	res, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("/health status: %d", res.StatusCode)
	}
	var body probeResponse
	if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if !body.OK {
		t.Fatalf("body: %+v", body)
	}
	if !st.healthCalled {
		t.Fatal("Health was not called")
	}

	res2, err := http.Get(srv.URL + "/ping")
	if err != nil {
		t.Fatal(err)
	}
	defer res2.Body.Close()
	if res2.StatusCode != http.StatusOK {
		t.Fatalf("/ping status: %d", res2.StatusCode)
	}
	var body2 probeResponse
	if err := json.NewDecoder(res2.Body).Decode(&body2); err != nil {
		t.Fatal(err)
	}
	if !body2.OK {
		t.Fatalf("body: %+v", body2)
	}
	if !st.pingCalled {
		t.Fatal("Ping was not called")
	}
}

// TestRoutes_Liveness_ErrorPath_LogsAtErrorLevel captures zerolog JSON to a buffer so we know
// the health/ping handlers log errors without changing the HTTP contract (still 200).
func TestRoutes_Liveness_ErrorPath_LogsAtErrorLevel(t *testing.T) {
	var buf bytes.Buffer
	log := zerolog.New(&buf).Level(zerolog.ErrorLevel)
	st := &stubLivenessProbe{
		healthErr: errors.New("health downstream"),
		pingErr:   errors.New("ping downstream"),
	}
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: st}))
	t.Cleanup(srv.Close)

	for _, path := range []string{"/health", "/ping"} {
		res, err := http.Get(srv.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, res.Body)
		_ = res.Body.Close()
		if res.StatusCode != http.StatusOK {
			t.Fatalf("%s status: %d", path, res.StatusCode)
		}
	}

	out := buf.String()
	if !strings.Contains(out, `"level":"error"`) {
		t.Fatalf("expected error-level logs, got %q", out)
	}
	if !strings.Contains(out, "health check failed") {
		t.Fatalf("missing health log line, got %q", out)
	}
	if !strings.Contains(out, "ping check failed") {
		t.Fatalf("missing ping log line, got %q", out)
	}
}

// TestRoutes_StatusCodeMatrix documents liveness (always 200 + ok) vs readiness (200 or 503).
func TestRoutes_StatusCodeMatrix(t *testing.T) {
	log := zerolog.Nop()

	tests := []struct {
		name     string
		path     string
		pinger   *fakePinger
		verify   *fakeVerifier
		wantCode int
		wantOK   bool
	}{
		{
			name:     "health_always_200_even_if_ready_deps_fail",
			path:     "/health",
			pinger:   &fakePinger{err: context.DeadlineExceeded},
			verify:   &fakeVerifier{},
			wantCode: http.StatusOK,
			wantOK:   true,
		},
		{
			name:     "ping_always_200_even_if_ready_deps_fail",
			path:     "/ping",
			pinger:   &fakePinger{err: context.DeadlineExceeded},
			verify:   &fakeVerifier{},
			wantCode: http.StatusOK,
			wantOK:   true,
		},
		{
			name:     "ready_200_when_deps_ok",
			path:     "/ready",
			pinger:   &fakePinger{},
			verify:   &fakeVerifier{},
			wantCode: http.StatusOK,
			wantOK:   true,
		},
		{
			name:     "ready_503_when_ping_fails",
			path:     "/ready",
			pinger:   &fakePinger{err: context.DeadlineExceeded},
			verify:   &fakeVerifier{},
			wantCode: http.StatusServiceUnavailable,
			wantOK:   false,
		},
		{
			name:     "ready_503_when_verify_fails",
			path:     "/ready",
			pinger:   &fakePinger{},
			verify:   &fakeVerifier{err: domain.ErrMigrationsNotAtHead},
			wantCode: http.StatusServiceUnavailable,
			wantOK:   false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := usecase.NewStatus(tt.pinger, tt.verify)
			srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: s}))
			t.Cleanup(srv.Close)

			res, err := http.Get(srv.URL + tt.path)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != tt.wantCode {
				t.Fatalf("status: got %d want %d", res.StatusCode, tt.wantCode)
			}
			var body probeResponse
			if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if body.OK != tt.wantOK {
				t.Fatalf("ok: got %v want %v", body.OK, tt.wantOK)
			}
		})
	}
}

// Liveness must stay 200 even when readiness dependencies fail.
func TestRoutes_HealthAndPing_OK_WhenReadyUnavailable(t *testing.T) {
	log := zerolog.Nop()
	s := usecase.NewStatus(&fakePinger{err: context.DeadlineExceeded}, &fakeVerifier{})
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: s}))
	t.Cleanup(srv.Close)

	for _, path := range []string{"/health", "/ping"} {
		t.Run(path, func(t *testing.T) {
			res, err := http.Get(srv.URL + path)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != http.StatusOK {
				t.Fatalf("status: %d", res.StatusCode)
			}
			var body probeResponse
			if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
				t.Fatal(err)
			}
			if !body.OK {
				t.Fatalf("body: %+v", body)
			}
		})
	}

	res, err := http.Get(srv.URL + "/ready")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("/ready status: %d", res.StatusCode)
	}
}

func TestRoute_Ready_OK(t *testing.T) {
	log := zerolog.Nop()
	s := usecase.NewStatus(&fakePinger{}, &fakeVerifier{})
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: s}))
	t.Cleanup(srv.Close)

	res, err := http.Get(srv.URL + "/ready")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status: %d", res.StatusCode)
	}
	var body probeResponse
	if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if !body.OK {
		t.Fatalf("body: %+v", body)
	}
}

func TestRoute_Ready_ServiceUnavailable(t *testing.T) {
	log := zerolog.Nop()
	s := usecase.NewStatus(&fakePinger{err: context.DeadlineExceeded}, &fakeVerifier{})
	srv := httptest.NewServer(NewRouter(Deps{Log: log, Status: s}))
	t.Cleanup(srv.Close)

	res, err := http.Get(srv.URL + "/ready")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("status: %d", res.StatusCode)
	}
	if ct := res.Header.Get("Content-Type"); ct != "application/json" {
		t.Fatalf("Content-Type: %q", ct)
	}
	b, _ := io.ReadAll(res.Body)
	var body probeResponse
	if err := json.Unmarshal(b, &body); err != nil {
		t.Fatal(err)
	}
	if body.OK {
		t.Fatalf("body: %+v", body)
	}
}
