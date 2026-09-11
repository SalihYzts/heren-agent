package adapter

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
)

// Linux adapter: systemd-first, GRUB fallback for boot targets.
type Linux struct {
	run      Runner
	approved ApprovedCommands
	readFile func(path string) (string, error)
	prevCPU  *cpuSample // last /proc/stat sample for cpu_pct deltas
}

func NewLinux(run Runner, approved ApprovedCommands) *Linux {
	return &Linux{run: run, approved: approved, readFile: func(p string) (string, error) {
		b, err := os.ReadFile(p)
		return string(b), err
	}}
}

func (l *Linux) Platform() string { return "linux" }

func (l *Linux) Capabilities() []string {
	return append([]string{"get_status", "get_metrics", "get_boot_entries", "lock", "launch_app", "stop_app",
		"restart_service", "run_approved_command", "sleep", "shutdown", "restart", "set_next_boot"}, serverCapabilities...)
}

// systemd unit / executable names: no path separators, no shell metacharacters.
var safeName = regexp.MustCompile(`^[A-Za-z0-9_.@:-]{1,128}$`)

func (l *Linux) Run(ctx context.Context, action string, params map[string]any) Result {
	switch action {
	case "get_status":
		return l.status(ctx)
	case "get_metrics":
		return l.metrics(ctx)
	case "get_boot_entries":
		entries, backend, err := l.bootEntries(ctx)
		if err != nil {
			return Fail(err)
		}
		return OK(map[string]any{"backend": backend, "entries": entries})
	case "lock":
		return l.exec(ctx, "loginctl", "lock-sessions")
	case "sleep":
		return l.exec(ctx, "systemctl", "suspend")
	case "shutdown":
		return l.exec(ctx, "systemctl", "poweroff")
	case "restart":
		return l.exec(ctx, "systemctl", "reboot")
	case "restart_service":
		name, ok := strParam(params, "name")
		if !ok || !safeName.MatchString(name) {
			return Failf("restart_service: invalid service name")
		}
		return l.exec(ctx, "systemctl", "restart", name)
	case "launch_app":
		app, ok := strParam(params, "app")
		if !ok || !safeName.MatchString(app) {
			return Failf("launch_app: app must be a bare executable name")
		}
		return l.exec(ctx, app)
	case "stop_app":
		app, ok := strParam(params, "app")
		if !ok || !safeName.MatchString(app) {
			return Failf("stop_app: invalid app name")
		}
		return l.exec(ctx, "pkill", "-x", app)
	case "run_approved_command":
		id, ok := strParam(params, "command_id")
		if !ok {
			return Failf("run_approved_command: command_id required")
		}
		argv, ok := l.approved[id]
		if !ok || len(argv) == 0 {
			return Failf("run_approved_command: '" + id + "' is not on the allowlist")
		}
		return l.exec(ctx, argv[0], argv[1:]...)
	case "set_next_boot":
		return l.setNextBoot(ctx, params)
	}
	if r, ok := l.runServer(ctx, action, params); ok {
		return r
	}
	return Failf("unsupported action: " + action)
}

func (l *Linux) exec(ctx context.Context, name string, args ...string) Result {
	out, err := l.run(ctx, name, args...)
	if err != nil {
		return Fail(fmt.Errorf("%s: %w", name, err))
	}
	return OK(map[string]any{"stdout": strings.TrimSpace(out)})
}

// ----------------------------------------------------------------- status/metrics

func (l *Linux) status(ctx context.Context) Result {
	host, _ := l.run(ctx, "hostname")
	out := map[string]any{"hostname": strings.TrimSpace(host), "platform": "linux"}
	if up, err := l.readFile("/proc/uptime"); err == nil {
		if f, err := strconv.ParseFloat(strings.Fields(up)[0], 64); err == nil {
			out["uptime_s"] = int(f)
		}
	}
	return OK(out)
}

func (l *Linux) metrics(ctx context.Context) Result {
	out := map[string]any{}
	if la, err := l.readFile("/proc/loadavg"); err == nil {
		f := strings.Fields(la)
		if len(f) >= 3 {
			out["load1"], _ = strconv.ParseFloat(f[0], 64)
			out["load5"], _ = strconv.ParseFloat(f[1], 64)
		}
	}
	if mi, err := l.readFile("/proc/meminfo"); err == nil {
		var total, avail, swapTotal, swapFree float64
		for _, line := range strings.Split(mi, "\n") {
			f := strings.Fields(line)
			if len(f) < 2 {
				continue
			}
			v, _ := strconv.ParseFloat(f[1], 64)
			switch f[0] {
			case "MemTotal:":
				total = v
			case "MemAvailable:":
				avail = v
			case "SwapTotal:":
				swapTotal = v
			case "SwapFree:":
				swapFree = v
			}
		}
		if total > 0 {
			out["ram_total_mb"] = int(total / 1024)
			out["ram_pct"] = int((total - avail) * 100 / total)
		}
		if swapTotal > 0 {
			out["swap_pct"] = int((swapTotal - swapFree) * 100 / swapTotal)
		}
	}
	if up, err := l.readFile("/proc/uptime"); err == nil {
		if f, err := strconv.ParseFloat(strings.Fields(up)[0], 64); err == nil {
			out["uptime_s"] = int(f)
		}
	}
	if pct, ok := l.cpuPct(); ok {
		out["cpu_pct"] = pct
	}
	if t, ok := l.tempC(); ok {
		out["temp_c"] = t
	}
	if disks := l.disks(ctx); len(disks) > 0 {
		worst := 0
		for _, d := range disks {
			if p := d["pct"].(int); p > worst {
				worst = p
			}
		}
		out["disks"] = disks
		out["disk_pct"] = worst
	}
	if rx, tx, ok := l.netTotals(); ok {
		out["net_rx_bytes"] = rx
		out["net_tx_bytes"] = tx
	}
	return OK(out)
}

// ----------------------------------------------------------------- boot targets

type bootEntry struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Def   bool   `json:"isDefault"`
}

var grubMenu = regexp.MustCompile(`(?m)^\s*menuentry\s+'([^']+)'`)

// bootEntries returns entries and which backend ("systemd-boot" | "grub") produced them.
func (l *Linux) bootEntries(ctx context.Context) ([]map[string]any, string, error) {
	if out, err := l.run(ctx, "bootctl", "list", "--json=short"); err == nil {
		var raw []bootEntry
		if err := json.Unmarshal([]byte(out), &raw); err == nil {
			entries := make([]map[string]any, 0, len(raw))
			for _, e := range raw {
				entries = append(entries, map[string]any{"id": e.ID, "title": e.Title, "default": e.Def})
			}
			return entries, "systemd-boot", nil
		}
	}
	cfg, err := l.readFile("/boot/grub/grub.cfg")
	if err == nil {
		entries := []map[string]any{}
		for i, m := range grubMenu.FindAllStringSubmatch(cfg, -1) {
			entries = append(entries, map[string]any{"id": m[1], "title": m[1], "default": i == 0})
		}
		return entries, "grub", nil
	}
	// Generic UEFI path (Limine, rEFInd, anything): firmware BootNext via efibootmgr.
	if out, err := l.run(ctx, "efibootmgr"); err == nil {
		entries := parseEfibootmgr(out)
		if len(entries) > 0 {
			return entries, "efi", nil
		}
	}
	return nil, "", errors.New("no supported bootloader found (systemd-boot, grub or efibootmgr)")
}

var efiEntry = regexp.MustCompile(`(?m)^Boot([0-9A-Fa-f]{4})(\*?)\s+([^	]+)`)
var efiOrder = regexp.MustCompile(`(?m)^BootOrder:\s*([0-9A-Fa-f]{4})`)

func parseEfibootmgr(out string) []map[string]any {
	first := ""
	if m := efiOrder.FindStringSubmatch(out); m != nil {
		first = strings.ToUpper(m[1])
	}
	entries := []map[string]any{}
	for _, m := range efiEntry.FindAllStringSubmatch(out, -1) {
		id := strings.ToUpper(m[1])
		entries = append(entries, map[string]any{
			"id": id, "title": strings.TrimSpace(m[3]), "default": id == first, "active": m[2] == "*",
		})
	}
	return entries
}

func (l *Linux) setNextBoot(ctx context.Context, params map[string]any) Result {
	entry, ok := strParam(params, "entry")
	if !ok {
		return Failf("set_next_boot: entry required")
	}
	entries, backend, err := l.bootEntries(ctx)
	if err != nil {
		return Fail(err)
	}
	found := false
	for _, e := range entries {
		if e["id"] == entry {
			found = true
			break
		}
	}
	if !found {
		return Failf("set_next_boot: unknown entry '" + entry + "'")
	}
	switch backend {
	case "systemd-boot":
		return l.exec(ctx, "bootctl", "set-oneshot", entry)
	case "grub":
		return l.exec(ctx, "grub-reboot", entry)
	case "efi":
		return l.exec(ctx, "efibootmgr", "-n", entry)
	}
	return Failf("set_next_boot: unsupported backend " + backend)
}
