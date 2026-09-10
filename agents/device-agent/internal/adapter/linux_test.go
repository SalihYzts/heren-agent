package adapter

import (
	"context"
	"errors"
	"strings"
	"testing"
)

type call struct {
	name string
	args []string
}

// fakeRunner records commands and returns canned stdout per command name.
func fakeRunner(calls *[]call, out map[string]string, fail map[string]error) Runner {
	return func(ctx context.Context, name string, args ...string) (string, error) {
		*calls = append(*calls, call{name, args})
		if err, ok := fail[name]; ok {
			return "", err
		}
		return out[name], nil
	}
}

func joined(c call) string { return c.name + " " + strings.Join(c.args, " ") }

func newLinux(calls *[]call, out map[string]string, fail map[string]error) *Linux {
	return NewLinux(fakeRunner(calls, out, fail), ApprovedCommands{"start-backend": {"systemctl", "--user", "start", "backend"}})
}

func TestLinuxCapabilitiesAreDeclared(t *testing.T) {
	l := newLinux(&[]call{}, nil, nil)
	caps := strings.Join(l.Capabilities(), ",")
	for _, want := range []string{"get_status", "get_metrics", "restart_service", "launch_app", "shutdown", "restart", "set_next_boot", "get_boot_entries", "run_approved_command", "lock"} {
		if !strings.Contains(caps, want) {
			t.Errorf("missing capability %s", want)
		}
	}
}

func TestGetStatusReportsHostnameAndUptime(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"hostname": "devpc\n"}, nil)
	l.readFile = func(p string) (string, error) {
		if p == "/proc/uptime" {
			return "12345.67 99999.0\n", nil
		}
		return "", errors.New("nope")
	}
	r := l.Run(context.Background(), "get_status", nil)
	if r.Status != "completed" || r.Output["hostname"] != "devpc" || r.Output["uptime_s"] != 12345 {
		t.Fatalf("bad status result: %+v", r)
	}
}

func TestGetMetricsParsesProcFiles(t *testing.T) {
	l := newLinux(&[]call{}, nil, nil)
	l.readFile = func(p string) (string, error) {
		switch p {
		case "/proc/loadavg":
			return "0.52 0.40 0.33 1/900 1234\n", nil
		case "/proc/meminfo":
			return "MemTotal:       16000000 kB\nMemFree:         2000000 kB\nMemAvailable:    8000000 kB\n", nil
		}
		return "", errors.New("nope")
	}
	r := l.Run(context.Background(), "get_metrics", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if r.Output["load1"] != 0.52 || r.Output["ram_pct"] != 50 {
		t.Errorf("unexpected metrics %+v", r.Output)
	}
}

func TestRestartServiceUsesSystemctlAndRejectsInjection(t *testing.T) {
	var calls []call
	l := newLinux(&calls, nil, nil)
	r := l.Run(context.Background(), "restart_service", map[string]any{"name": "nginx"})
	if r.Status != "completed" || joined(calls[0]) != "systemctl restart nginx" {
		t.Fatalf("%+v %v", r, calls)
	}
	for _, bad := range []string{"nginx; rm -rf /", "a b", "../x", ""} {
		r := l.Run(context.Background(), "restart_service", map[string]any{"name": bad})
		if r.Status != "failed" {
			t.Errorf("accepted bad service name %q", bad)
		}
	}
}

func TestShutdownAndRestartUseSystemctl(t *testing.T) {
	var calls []call
	l := newLinux(&calls, nil, nil)
	l.Run(context.Background(), "shutdown", nil)
	l.Run(context.Background(), "restart", nil)
	l.Run(context.Background(), "sleep", nil)
	l.Run(context.Background(), "lock", nil)
	got := []string{joined(calls[0]), joined(calls[1]), joined(calls[2]), joined(calls[3])}
	want := []string{"systemctl poweroff", "systemctl reboot", "systemctl suspend", "loginctl lock-sessions"}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("call %d: got %q want %q", i, got[i], want[i])
		}
	}
}

func TestLaunchAppOnlyAllowsBareExecutableNames(t *testing.T) {
	var calls []call
	l := newLinux(&calls, nil, nil)
	if r := l.Run(context.Background(), "launch_app", map[string]any{"app": "firefox"}); r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if calls[0].name != "firefox" {
		t.Errorf("launched %v", calls[0])
	}
	if r := l.Run(context.Background(), "launch_app", map[string]any{"app": "/bin/sh -c 'x'"}); r.Status != "failed" {
		t.Error("accepted shell string")
	}
}

func TestRunApprovedCommandOnlyFromAllowlist(t *testing.T) {
	var calls []call
	l := newLinux(&calls, nil, nil)
	r := l.Run(context.Background(), "run_approved_command", map[string]any{"command_id": "start-backend"})
	if r.Status != "completed" || joined(calls[0]) != "systemctl --user start backend" {
		t.Fatalf("%+v %v", r, calls)
	}
	r = l.Run(context.Background(), "run_approved_command", map[string]any{"command_id": "not-listed"})
	if r.Status != "failed" || len(calls) != 1 {
		t.Error("ran a command that is not on the allowlist")
	}
	r = l.Run(context.Background(), "run_approved_command", map[string]any{"command": "ls"})
	if r.Status != "failed" {
		t.Error("accepted free-text command")
	}
}

func TestBootEntriesFromBootctl(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"bootctl": `[{"id":"arch.conf","title":"Arch Linux","isDefault":true},{"id":"auto-windows","title":"Windows Boot Manager","isDefault":false}]`}, nil)
	r := l.Run(context.Background(), "get_boot_entries", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	entries := r.Output["entries"].([]map[string]any)
	if len(entries) != 2 || entries[1]["id"] != "auto-windows" || entries[0]["default"] != true {
		t.Errorf("%+v", entries)
	}
}

func TestSetNextBootUsesBootloaderEntryOnSystemdBoot(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"bootctl": `[{"id":"auto-windows","title":"Windows"}]`}, nil)
	r := l.Run(context.Background(), "set_next_boot", map[string]any{"entry": "auto-windows"})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	last := joined(calls[len(calls)-1])
	if last != "bootctl set-oneshot auto-windows" {
		t.Errorf("got %q", last)
	}
	// unknown entry must be refused before touching the bootloader
	calls = nil
	r = l.Run(context.Background(), "set_next_boot", map[string]any{"entry": "evil"})
	if r.Status != "failed" || len(calls) != 1 {
		t.Errorf("unknown entry not refused: %+v calls=%v", r, calls)
	}
}

func TestSetNextBootFallsBackToGrubReboot(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"grub-reboot": ""}, map[string]error{"bootctl": errors.New("not systemd-boot")})
	l.readFile = func(p string) (string, error) {
		if p == "/boot/grub/grub.cfg" {
			return "menuentry 'Arch Linux' --class arch {\n}\nmenuentry 'Windows Boot Manager (on /dev/nvme0n1p1)' --class windows {\n}\n", nil
		}
		return "", errors.New("nope")
	}
	r := l.Run(context.Background(), "get_boot_entries", nil)
	entries := r.Output["entries"].([]map[string]any)
	if len(entries) != 2 || entries[1]["title"] != "Windows Boot Manager (on /dev/nvme0n1p1)" {
		t.Fatalf("%+v", r)
	}
	r = l.Run(context.Background(), "set_next_boot", map[string]any{"entry": "Windows Boot Manager (on /dev/nvme0n1p1)"})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	last := calls[len(calls)-1]
	if last.name != "grub-reboot" || last.args[0] != "Windows Boot Manager (on /dev/nvme0n1p1)" {
		t.Errorf("%v", last)
	}
}

func TestUnknownActionFails(t *testing.T) {
	l := newLinux(&[]call{}, nil, nil)
	if r := l.Run(context.Background(), "format_disk", nil); r.Status != "failed" {
		t.Error("unknown action did not fail")
	}
}
