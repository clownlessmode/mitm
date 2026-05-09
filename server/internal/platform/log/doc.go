// Package log configures shared structured logging for the service using zerolog.
//
// This package’s name shadows the Go standard library [log] package. Import it
// with an alias in callers (for example: plog "…/internal/platform/log") to
// avoid confusion and import clashes.
//
// [log]: https://pkg.go.dev/log
package log
