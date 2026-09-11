package adapter

import (
	"context"
	"errors"
	"strings"
	"testing"
)

// ----------------------------------------------------------------- richer metrics

func TestGetMetricsReportsCpuDiskTempAndNet(t *testing.T) {
	l := newLinux(&[]call{}, map[string]string{
		"df": "Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/nvme0n1p2 996008244 452139680 543004864 46% /\nefivarfs 256 53 199 21% /sys/firmware/efi/efivars\n/dev/sda1 1000000 900000 100000 90% /srv/data\n",
	}, nil)
	stat := []string{
		"cpu  1000 0 500 8500 0 0 0 0 0 0\n", // idle 8500 / total 10000
		"cpu  1400 0 700 8900 0 0 0 0 0 0\n", // Δ: busy 600 / total 1000 → 60%
	}
	n := 0
	l.readFile = func(p string) (string, error) {
		switch p {
		case "/proc/loadavg":
			return "0.52 0.40 0.33 1/900 1234\n", nil
		case "/proc/meminfo":
			return "MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\nSwapTotal: 4000000 kB\nSwapFree: 3000000 kB\n", nil
		case "/proc/stat":
			s := stat[n%2]
			n++
			return s, nil
		case "/proc/uptime":
			return "3600.5 99\n", nil
		case "/sys/class/thermal/thermal_zone0/type":
			return "acpitz\n", nil
		case "/sys/class/thermal/thermal_zone0/temp":
			return "67000\n", nil
		case "/sys/class/thermal/thermal_zone1/type":
			return "x86_pkg_temp\n", nil
		case "/sys/class/thermal/thermal_zone1/temp":
			return "71000\n", nil
		case "/proc/net/dev":
			return "Inter-|   Receive                                                |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n    lo: 100 1 0 0 0 0 0 0 100 1 0 0 0 0 0 0\n  eno1: 5000 10 0 0 0 0 0 0 2000 5 0 0 0 0 0 0\n wlan0: 7000 10 0 0 0 0 0 0 1000 5 0 0 0 0 0 0\n", nil
		}
		return "", errors.New("nope")
	}
	first := l.Run(context.Background(), "get_metrics", nil)
	if first.Status != "completed" {
		t.Fatal(first.Error)
	}
	if _, has := first.Output["cpu_pct"]; has {
		t.Error("first sample has no delta yet → no cpu_pct")
	}
	r := l.Run(context.Background(), "get_metrics", nil)
	if r.Output["cpu_pct"] != 60 {
		t.Errorf("cpu_pct from /proc/stat delta: got %v", r.Output["cpu_pct"])
	}
	if r.Output["swap_pct"] != 25 || r.Output["uptime_s"] != 3600 {
		t.Errorf("swap/uptime: %+v", r.Output)
	}
	if r.Output["temp_c"] != 71 { // hottest zone, x86_pkg_temp preferred anyway
		t.Errorf("temp_c: %v", r.Output["temp_c"])
	}
	disks, _ := r.Output["disks"].([]map[string]any)
	if len(disks) != 2 || disks[0]["mount"] != "/" || disks[0]["pct"] != 46 || disks[1]["pct"] != 90 {
		t.Errorf("disks (efivarfs must be skipped): %+v", disks)
	}
	if r.Output["disk_pct"] != 90 {
		t.Errorf("disk_pct = worst mount: %v", r.Output["disk_pct"])
	}
	// net: totals excluding lo, in bytes
	if r.Output["net_rx_bytes"] != int64(12000) || r.Output["net_tx_bytes"] != int64(3000) {
		t.Errorf("net: %+v", r.Output)
	}
}

// ----------------------------------------------------------------- services

const listUnits = `alsa-restore.service                                  loaded    active   exited  Save/Restore Sound Card State
nginx.service                                         loaded    active   running A high performance web server
postgresql.service                                    loaded    failed   failed  PostgreSQL database server
sshd.service                                          loaded    active   running OpenSSH Daemon
hermes-gateway.service                                loaded    inactive dead    Hermes gateway
`

func TestListServicesParsesSystemctlAndFlagsFailed(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"systemctl": listUnits}, nil)
	r := l.Run(context.Background(), "list_services", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if !strings.Contains(joined(calls[0]), "list-units --type=service --all --no-pager --no-legend --plain") {
		t.Errorf("wrong systemctl invocation: %s", joined(calls[0]))
	}
	svcs, _ := r.Output["services"].([]map[string]any)
	if len(svcs) != 5 {
		t.Fatalf("want 5 services, got %d", len(svcs))
	}
	byName := map[string]map[string]any{}
	for _, s := range svcs {
		byName[s["name"].(string)] = s
	}
	if byName["nginx"]["state"] != "running" || byName["nginx"]["description"] != "A high performance web server" {
		t.Errorf("nginx: %+v", byName["nginx"])
	}
	if byName["postgresql"]["state"] != "failed" || byName["hermes-gateway"]["state"] != "inactive" || byName["alsa-restore"]["state"] != "exited" {
		t.Errorf("states: %+v %+v %+v", byName["postgresql"], byName["hermes-gateway"], byName["alsa-restore"])
	}
	if r.Output["failed"] != 1 {
		t.Errorf("failed count: %v", r.Output["failed"])
	}
}

func TestServiceControlUsesSystemctlVerbsAndRejectsInjection(t *testing.T) {
	for _, tc := range []struct{ action, verb string }{
		{"start_service", "start"}, {"stop_service", "stop"}, {"restart_service", "restart"},
		{"enable_service", "enable"}, {"disable_service", "disable"},
	} {
		var calls []call
		l := newLinux(&calls, nil, nil)
		r := l.Run(context.Background(), tc.action, map[string]any{"name": "nginx"})
		if r.Status != "completed" || joined(calls[0]) != "systemctl "+tc.verb+" nginx" {
			t.Errorf("%s: %+v %v", tc.action, r, calls)
		}
		bad := l.Run(context.Background(), tc.action, map[string]any{"name": "nginx; rm -rf /"})
		if bad.Status != "failed" || len(calls) != 1 {
			t.Errorf("%s must reject shell metacharacters", tc.action)
		}
	}
}

func TestServiceLogsUsesJournalctlWithBoundedLines(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"journalctl": "2026-09-11T12:00:00+0300 pc nginx[1]: started\n2026-09-11T12:00:01+0300 pc nginx[1]: ready\n"}, nil)
	r := l.Run(context.Background(), "service_logs", map[string]any{"name": "nginx", "lines": float64(50)})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if joined(calls[0]) != "journalctl -u nginx -n 50 --no-pager -o short-iso" {
		t.Errorf("journalctl args: %s", joined(calls[0]))
	}
	lines, _ := r.Output["lines"].([]string)
	if len(lines) != 2 || !strings.HasSuffix(lines[1], "ready") {
		t.Errorf("lines: %+v", lines)
	}
	// bounds: default 100, cap 1000, never negative
	calls = nil
	l.Run(context.Background(), "service_logs", map[string]any{"name": "nginx"})
	if !strings.Contains(joined(calls[0]), "-n 100") {
		t.Errorf("default lines: %s", joined(calls[0]))
	}
	calls = nil
	l.Run(context.Background(), "service_logs", map[string]any{"name": "nginx", "lines": float64(99999)})
	if !strings.Contains(joined(calls[0]), "-n 1000") {
		t.Errorf("capped lines: %s", joined(calls[0]))
	}
	// system journal (no unit): last N lines of everything, for Hermes diagnosis
	calls = nil
	l.Run(context.Background(), "system_logs", map[string]any{"lines": float64(20)})
	if joined(calls[0]) != "journalctl -n 20 --no-pager -o short-iso -p warning" {
		t.Errorf("system_logs args: %s", joined(calls[0]))
	}
}

// ----------------------------------------------------------------- containers (optional)

func TestListContainersUsesDockerOrPodmanAndDegradesGracefully(t *testing.T) {
	psOut := `{"Names":"web","Image":"nginx:1.27","State":"running","Status":"Up 3 hours"}
{"Names":"db","Image":"postgres:16","State":"exited","Status":"Exited (1) 2 hours ago"}
`
	var calls []call
	l := newLinux(&calls, map[string]string{"docker": psOut}, nil)
	r := l.Run(context.Background(), "list_containers", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	cs, _ := r.Output["containers"].([]map[string]any)
	if len(cs) != 2 || cs[0]["name"] != "web" || cs[0]["state"] != "running" || cs[1]["image"] != "postgres:16" {
		t.Errorf("containers: %+v", cs)
	}
	if r.Output["runtime"] != "docker" || !strings.Contains(joined(calls[len(calls)-1]), "ps -a --format {{json .}}") {
		t.Errorf("runtime/args: %v %s", r.Output["runtime"], joined(calls[len(calls)-1]))
	}
	// docker missing → podman
	calls = nil
	l = newLinux(&calls, map[string]string{"podman": psOut}, map[string]error{"docker": errors.New("not found")})
	r = l.Run(context.Background(), "list_containers", nil)
	if r.Status != "completed" || r.Output["runtime"] != "podman" {
		t.Errorf("podman fallback: %+v", r)
	}
	// neither → completed with an empty list and a note, not a failure (the server may just not run containers)
	l = newLinux(&calls, nil, map[string]error{"docker": errors.New("nf"), "podman": errors.New("nf")})
	r = l.Run(context.Background(), "list_containers", nil)
	if r.Status != "completed" || r.Output["runtime"] != "none" {
		t.Errorf("no runtime: %+v", r)
	}
	// container control
	calls = nil
	l = newLinux(&calls, map[string]string{"docker": ""}, nil)
	l.Run(context.Background(), "restart_container", map[string]any{"name": "web"})
	if joined(calls[len(calls)-1]) != "docker restart web" {
		t.Errorf("restart_container: %v", calls)
	}
}

func TestNewCapabilitiesAreDeclared(t *testing.T) {
	caps := strings.Join(newLinux(&[]call{}, nil, nil).Capabilities(), ",")
	for _, want := range []string{"list_services", "start_service", "stop_service", "enable_service", "disable_service", "service_logs", "system_logs", "list_containers", "start_container", "stop_container", "restart_container"} {
		if !strings.Contains(caps, want) {
			t.Errorf("missing capability %s", want)
		}
	}
}
