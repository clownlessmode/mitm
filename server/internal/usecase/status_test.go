package usecase

import (
	"context"
	"errors"
	"testing"

	"github.com/purpletooth/mitm_scripts/server/internal/domain"
)

type fakePinger struct {
	err error
}

func (f *fakePinger) Ping(_ context.Context) error { return f.err }

type fakeVerifier struct {
	err error
}

func (f *fakeVerifier) VerifyMigrationsAtHead(_ context.Context) error { return f.err }

type ctxErrPinger struct{}

func (ctxErrPinger) Ping(ctx context.Context) error { return ctx.Err() }

func TestStatus_Health(t *testing.T) {
	s := NewStatus(&fakePinger{}, &fakeVerifier{})
	if err := s.Health(t.Context()); err != nil {
		t.Fatalf("Health: %v", err)
	}
}

func TestStatus_Ping(t *testing.T) {
	s := NewStatus(&fakePinger{}, &fakeVerifier{})
	if err := s.Ping(t.Context()); err != nil {
		t.Fatalf("Ping: %v", err)
	}
}

func TestStatus_Ready_OK(t *testing.T) {
	s := NewStatus(&fakePinger{err: nil}, &fakeVerifier{err: nil})
	if err := s.Ready(t.Context()); err != nil {
		t.Fatalf("Ready: %v", err)
	}
}

func TestStatus_Ready_PingFails(t *testing.T) {
	want := errors.New("ping failed")
	s := NewStatus(&fakePinger{err: want}, &fakeVerifier{err: nil})
	err := s.Ready(t.Context())
	if !errors.Is(err, want) {
		t.Fatalf("got %v want %v", err, want)
	}
}

func TestStatus_Ready_VerifyFails(t *testing.T) {
	want := domain.ErrMigrationsNotAtHead
	s := NewStatus(&fakePinger{err: nil}, &fakeVerifier{err: want})
	err := s.Ready(t.Context())
	if !errors.Is(err, want) {
		t.Fatalf("got %v want %v", err, want)
	}
}

func TestStatus_Ready_ContextCanceled(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	s := NewStatus(ctxErrPinger{}, &fakeVerifier{})
	err := s.Ready(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("got %v want %v", err, context.Canceled)
	}
}
