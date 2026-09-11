package adapter

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
)

// Server-facing capabilities of the Linux adapter: richer metrics, systemd services,
// journal access and (optional) docker/podman containers. Same rules as linux.go:
// no shell, fixed argv, validated names, bounded output.

var serverCapabilities = []string{
	"list_services", "start_service", "stop_service", "enable_service", "disable_service",
	"service_logs", "system_logs",
	"list_containers", "start_container", "stop_container", "restart_container",
}

const (
	defaultLogLines = 100
	maxLogLines     = 1000
)

// runServer handles the server actions; ok=false means "not mine".
func (l *Linux) runServer(ctx context.Context, action string, params map[string]any) (Result, bool) {
	switch action {
	case "list_services":
		return l.listServices(ctx), true
	case "start_service", "stop_service", "enable_service", "disable_service":
		name, ok := strParam(params, "name")
		if !ok || !safeName.MatchString(name) {
			return Failf(action + ": invalid service name"), true
		}
		return l.exec(ctx, "systemctl", strings.TrimSuffix(action, "_service"), name), true
	case "service_logs":
		name, ok := strParam(params, "name")
		if !ok || !safeName.MatchString(name) {
			return Failf("service_logs: invalid service name"), true
		}
		return l.journal(ctx, "-u", name, "-n", strconv.Itoa(logLines(params)), "--no-pager", "-o", "short-iso"), true
	case "system_logs":
		return l.journal(ctx, "-n", strconv.Itoa(logLines(params)), "--no-pager", "-o", "short-iso", "-p", "warning"), true
	case "list_containers":
		return l.listContainers(ctx), true
	case "start_container", "stop_container", "restart_container":
		name, ok := strParam(params, "name")
		if !ok || !safeName.MatchString(name) {
			return Failf(action + ": invalid container name"), true
		}
		rt := l.containerRuntime(ctx)
		if rt == "" {
			return Failf(action + ": no container runtime (docker/podman) on this machine"), true
		}
		return l.exec(ctx, rt, strings.TrimSuffix(action, "_container"), name), true
	}
	return Result{}, false
}

func logLines(params map[string]any) int {
	n := defaultLogLines
	if v, ok := params["lines"]; ok {
		switch x := v.(type) {
		case float64:
			n = int(x)
		case int:
			n = x
		}
	}
	if n < 1 {
		n = 1
	}
	if n > maxLogLines {
		n = maxLogLines
	}
	return n
}

func (l *Linux) journal(ctx context.Context, args ...string) Result {
	out, err := l.run(ctx, "journalctl", args...)
	if err != nil {
		return Fail(err)
	}
	lines := []string{}
	for _, ln := range strings.Split(strings.TrimRight(out, "\n"), "\n") {
		if ln != "" {
			lines = append(lines, ln)
		}
	}
	return OK(map[string]any{"lines": lines})
}

// ----------------------------------------------------------------- services

// systemctl list-units --plain: NAME LOAD ACTIVE SUB DESCRIPTION…
func (l *Linux) listServices(ctx context.Context) Result {
	out, err := l.run(ctx, "systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend", "--plain")
	if err != nil {
		return Fail(err)
	}
	services := []map[string]any{}
	failed := 0
	for _, ln := range strings.Split(out, "\n") {
		f := strings.Fields(ln)
		if len(f) < 4 || !strings.HasSuffix(f[0], ".service") {
			continue
		}
		active, sub := f[2], f[3]
		state := sub // running / exited / dead / failed …
		if active == "failed" || sub == "failed" {
			state = "failed"
			failed++
		} else if active == "inactive" {
			state = "inactive"
		}
		services = append(services, map[string]any{
			"name":        strings.TrimSuffix(f[0], ".service"),
			"state":       state,
			"description": strings.Join(f[4:], " "),
		})
	}
	return OK(map[string]any{"services": services, "failed": failed})
}

// ----------------------------------------------------------------- containers

func (l *Linux) containerRuntime(ctx context.Context) string {
	for _, rt := range []string{"docker", "podman"} {
		if _, err := l.run(ctx, rt, "version", "--format", "{{.Client.Version}}"); err == nil {
			return rt
		}
	}
	return ""
}

func (l *Linux) listContainers(ctx context.Context) Result {
	rt := l.containerRuntime(ctx)
	if rt == "" {
		return OK(map[string]any{"runtime": "none", "containers": []map[string]any{}})
	}
	out, err := l.run(ctx, rt, "ps", "-a", "--format", "{{json .}}")
	if err != nil {
		return Fail(err)
	}
	containers := []map[string]any{}
	for _, ln := range strings.Split(out, "\n") {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		var row struct {
			Names  string `json:"Names"`
			Image  string `json:"Image"`
			State  string `json:"State"`
			Status string `json:"Status"`
		}
		if json.Unmarshal([]byte(ln), &row) != nil {
			continue
		}
		containers = append(containers, map[string]any{
			"name": row.Names, "image": row.Image, "state": row.State, "status": row.Status,
		})
	}
	return OK(map[string]any{"runtime": rt, "containers": containers})
}

// ----------------------------------------------------------------- metrics extras

// cpuSample is the previous /proc/stat reading; cpu_pct is a delta so the first call has none.
type cpuSample struct{ busy, total float64 }

func parseCPU(stat string) (cpuSample, error) {
	for _, ln := range strings.Split(stat, "\n") {
		f := strings.Fields(ln)
		if len(f) < 5 || f[0] != "cpu" {
			continue
		}
		var total, idle float64
		for i, v := range f[1:] {
			x, _ := strconv.ParseFloat(v, 64)
			total += x
			if i == 3 || i == 4 { // idle, iowait
				idle += x
			}
		}
		return cpuSample{busy: total - idle, total: total}, nil
	}
	return cpuSample{}, errors.New("no cpu line")
}

func (l *Linux) cpuPct() (int, bool) {
	stat, err := l.readFile("/proc/stat")
	if err != nil {
		return 0, false
	}
	now, err := parseCPU(stat)
	if err != nil {
		return 0, false
	}
	prev := l.prevCPU
	l.prevCPU = &now
	if prev == nil || now.total <= prev.total {
		return 0, false
	}
	return int((now.busy - prev.busy) * 100 / (now.total - prev.total)), true
}

// df -P (POSIX): Filesystem 1024-blocks Used Available Capacity Mounted-on
func (l *Linux) disks(ctx context.Context) []map[string]any {
	out, err := l.run(ctx, "df", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay", "-x", "efivarfs")
	if err != nil {
		return nil
	}
	disks := []map[string]any{}
	seen := map[string]bool{}
	for _, ln := range strings.Split(out, "\n")[1:] {
		f := strings.Fields(ln)
		if len(f) < 6 || !strings.HasPrefix(f[0], "/dev/") || seen[f[0]] {
			continue // pseudo filesystems (efivarfs etc.) and bind-mount duplicates
		}
		seen[f[0]] = true
		pct, _ := strconv.Atoi(strings.TrimSuffix(f[4], "%"))
		total, _ := strconv.ParseInt(f[1], 10, 64)
		used, _ := strconv.ParseInt(f[2], 10, 64)
		disks = append(disks, map[string]any{
			"mount": f[5], "device": f[0], "pct": pct, "total_gb": float64(total) / 1048576, "used_gb": float64(used) / 1048576,
		})
	}
	return disks
}

// hottest thermal zone; x86_pkg_temp/coretemp-like names win ties as the "CPU" reading.
func (l *Linux) tempC() (int, bool) {
	best, found := -1000, false
	for i := 0; i < 16; i++ {
		base := "/sys/class/thermal/thermal_zone" + strconv.Itoa(i)
		raw, err := l.readFile(base + "/temp")
		if err != nil {
			break
		}
		v, err := strconv.Atoi(strings.TrimSpace(raw))
		if err != nil {
			continue
		}
		if v/1000 > best {
			best, found = v/1000, true
		}
	}
	return best, found
}

func (l *Linux) netTotals() (rx, tx int64, ok bool) {
	raw, err := l.readFile("/proc/net/dev")
	if err != nil {
		return 0, 0, false
	}
	for _, ln := range strings.Split(raw, "\n") {
		i := strings.Index(ln, ":")
		if i < 0 {
			continue
		}
		iface := strings.TrimSpace(ln[:i])
		f := strings.Fields(ln[i+1:])
		if iface == "lo" || len(f) < 9 {
			continue
		}
		r, _ := strconv.ParseInt(f[0], 10, 64)
		t, _ := strconv.ParseInt(f[8], 10, 64)
		rx += r
		tx += t
		ok = true
	}
	return rx, tx, ok
}
