package log

import (
	"io"
	"os"
	"time"

	"github.com/rs/zerolog"
)

// New returns a logger writing to stdout at level.
//
// When humanReadable is true, output uses [zerolog.ConsoleWriter]: readable
// timestamps, level names, and field formatting; color is used when stdout is
// a terminal (non-TTY environments such as CI may not show ANSI colors).
// When humanReadable is false, output is zerolog’s compact JSON format.
func New(level zerolog.Level, humanReadable bool) zerolog.Logger {
	var out io.Writer = os.Stdout
	if humanReadable {
		out = zerolog.ConsoleWriter{
			Out:        os.Stdout,
			TimeFormat: time.DateTime,
		}
	}

	return zerolog.New(out).Level(level).With().Timestamp().Logger()
}
