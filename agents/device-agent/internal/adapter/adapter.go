// Package adapter defines the OS abstraction. Core never sees OS specifics.
package adapter

import "context"

// Result mirrors the core's ActionResult payload.
type Result struct {
	Status string         `json:"status"` // completed | failed
	Output map[string]any `json:"output,omitempty"`
	Error  string         `json:"error,omitempty"`
}

func OK(output map[string]any) Result {
	if output == nil {
		output = map[string]any{}
	}
	return Result{Status: "completed", Output: output}
}

func Fail(err error) Result { return Result{Status: "failed", Error: err.Error()} }

func Failf(msg string) Result { return Result{Status: "failed", Error: msg} }

// Runner executes an external command. Injected so adapters are testable without root.
type Runner func(ctx context.Context, name string, args ...string) (stdout string, err error)

// Adapter is implemented per OS.
type Adapter interface {
	Platform() string
	Capabilities() []string
	Run(ctx context.Context, action string, params map[string]any) Result
}

// ApprovedCommands maps command_id → argv. Only these can be run via run_approved_command.
type ApprovedCommands map[string][]string

func strParam(params map[string]any, key string) (string, bool) {
	v, ok := params[key]
	if !ok {
		return "", false
	}
	s, ok := v.(string)
	return s, ok && s != ""
}
