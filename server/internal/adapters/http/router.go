package httpadapter

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/rs/zerolog"
)

// StatusProbe is the status surface used by probe handlers (implemented by *usecase.Status).
type StatusProbe interface {
	Health(ctx context.Context) error
	Ping(ctx context.Context) error
	Ready(ctx context.Context) error
}

// Deps carries logger and use-case dependencies for the HTTP surface.
type Deps struct {
	Log    zerolog.Logger
	Status StatusProbe
}

type probeResponse struct {
	OK bool `json:"ok"`
}

// NewRouter returns a chi router with /health, /ping, and /ready.
// /health and /ping are liveness probes: always 200 with {"ok":true}.
// /ready is readiness: 200 with {"ok":true} or 503 with {"ok":false}.
func NewRouter(d Deps) http.Handler {
	h := handlers{d: d}
	r := chi.NewRouter()
	r.Get("/health", h.health)
	r.Get("/ping", h.ping)
	r.Get("/ready", h.ready)
	return r
}

type handlers struct {
	d Deps
}

func (h handlers) health(w http.ResponseWriter, r *http.Request) {
	if err := h.d.Status.Health(r.Context()); err != nil {
		h.d.Log.Error().Err(err).Msg("health check failed")
	}
	writeProbeJSON(w, http.StatusOK, true)
}

func (h handlers) ping(w http.ResponseWriter, r *http.Request) {
	if err := h.d.Status.Ping(r.Context()); err != nil {
		h.d.Log.Error().Err(err).Msg("ping check failed")
	}
	writeProbeJSON(w, http.StatusOK, true)
}

func (h handlers) ready(w http.ResponseWriter, r *http.Request) {
	if err := h.d.Status.Ready(r.Context()); err != nil {
		h.d.Log.Error().Err(err).Msg("ready check failed")
		writeProbeJSON(w, http.StatusServiceUnavailable, false)
		return
	}
	writeProbeJSON(w, http.StatusOK, true)
}

func writeProbeJSON(w http.ResponseWriter, status int, ok bool) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(probeResponse{OK: ok})
}
