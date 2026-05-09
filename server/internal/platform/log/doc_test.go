package log

import (
	"testing"

	"github.com/rs/zerolog"
)

func TestPackageCompilesUnderGoTest(t *testing.T) {
	// Smoke: constructor runs without panic.
	_ = New(zerolog.Disabled, false)
	_ = New(zerolog.DebugLevel, true)
}

func TestParseLevel_commonStrings(t *testing.T) {
	tests := []struct {
		in   string
		want zerolog.Level
	}{
		{"trace", zerolog.TraceLevel},
		{"debug", zerolog.DebugLevel},
		{"info", zerolog.InfoLevel},
		{"warn", zerolog.WarnLevel},
		{"error", zerolog.ErrorLevel},
	}
	for _, tt := range tests {
		t.Run(tt.in, func(t *testing.T) {
			got, err := zerolog.ParseLevel(tt.in)
			if err != nil {
				t.Fatalf("ParseLevel(%q): %v", tt.in, err)
			}
			if got != tt.want {
				t.Fatalf("ParseLevel(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}
