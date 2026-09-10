package adapter

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

// Windows adapter. Boot target switching uses the UEFI firmware boot manager
// (bcdedit /set {fwbootmgr} bootsequence <GUID>) — a one-shot BootNext, so GRUB /
// systemd-boot on the Linux side is never touched. Requires an elevated agent service.
type Windows struct {
	run      Runner
	approved ApprovedCommands
}

func NewWindows(run Runner, approved ApprovedCommands) *Windows {
	return &Windows{run: run, approved: approved}
}

func (w *Windows) Platform() string { return "windows" }

func (w *Windows) Capabilities() []string {
	return []string{"get_status", "get_metrics", "get_boot_entries", "lock", "launch_app", "stop_app",
		"restart_service", "run_approved_command", "sleep", "shutdown", "restart", "set_next_boot"}
}

var winServiceName = regexp.MustCompile(`^[A-Za-z0-9_.\- ]{1,128}$`)
var bcdGUID = regexp.MustCompile(`^\{[0-9a-fA-F-]{36}\}$|^\{bootmgr\}$`)

func (w *Windows) Run(ctx context.Context, action string, params map[string]any) Result {
	switch action {
	case "get_status":
		host, _ := w.run(ctx, "hostname")
		return OK(map[string]any{"hostname": strings.TrimSpace(host), "platform": "windows"})
	case "get_metrics":
		return w.metrics(ctx)
	case "get_boot_entries":
		entries, err := w.bootEntries(ctx)
		if err != nil {
			return Fail(err)
		}
		return OK(map[string]any{"backend": "uefi-fwbootmgr", "entries": entries})
	case "lock":
		return w.exec(ctx, "rundll32.exe", "user32.dll,LockWorkStation")
	case "sleep":
		return w.exec(ctx, "rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0")
	case "shutdown":
		return w.exec(ctx, "shutdown", "/s", "/t", "5")
	case "restart":
		return w.exec(ctx, "shutdown", "/r", "/t", "5")
	case "restart_service":
		name, ok := strParam(params, "name")
		if !ok || !winServiceName.MatchString(name) {
			return Failf("restart_service: invalid service name")
		}
		return w.exec(ctx, "powershell", "-NoProfile", "-Command",
			fmt.Sprintf("Restart-Service -Name '%s' -Force", name))
	case "launch_app":
		app, ok := strParam(params, "app")
		if !ok || !safeName.MatchString(app) {
			return Failf("launch_app: app must be a bare executable name")
		}
		return w.exec(ctx, app)
	case "stop_app":
		app, ok := strParam(params, "app")
		if !ok || !safeName.MatchString(app) {
			return Failf("stop_app: invalid app name")
		}
		return w.exec(ctx, "taskkill", "/IM", app+".exe", "/F")
	case "run_approved_command":
		id, ok := strParam(params, "command_id")
		if !ok {
			return Failf("run_approved_command: command_id required")
		}
		argv, ok := w.approved[id]
		if !ok || len(argv) == 0 {
			return Failf("run_approved_command: '" + id + "' is not on the allowlist")
		}
		return w.exec(ctx, argv[0], argv[1:]...)
	case "set_next_boot":
		return w.setNextBoot(ctx, params)
	}
	return Failf("unsupported action: " + action)
}

func (w *Windows) exec(ctx context.Context, name string, args ...string) Result {
	out, err := w.run(ctx, name, args...)
	if err != nil {
		return Fail(fmt.Errorf("%s: %w", name, err))
	}
	return OK(map[string]any{"stdout": strings.TrimSpace(out)})
}

func (w *Windows) metrics(ctx context.Context) Result {
	out, err := w.run(ctx, "powershell", "-NoProfile", "-Command",
		`$os=Get-CimInstance Win32_OperatingSystem; $cpu=(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; `+
			`"$cpu $($os.TotalVisibleMemorySize) $($os.FreePhysicalMemory)"`)
	if err != nil {
		return Fail(err)
	}
	f := strings.Fields(out)
	res := map[string]any{}
	if len(f) == 3 {
		var cpu, total, free float64
		fmt.Sscanf(f[0], "%f", &cpu)
		fmt.Sscanf(f[1], "%f", &total)
		fmt.Sscanf(f[2], "%f", &free)
		res["cpu_pct"] = int(cpu)
		if total > 0 {
			res["ram_total_mb"] = int(total / 1024)
			res["ram_pct"] = int((total - free) * 100 / total)
		}
	}
	return OK(res)
}

var bcdIdent = regexp.MustCompile(`(?m)^identifier\s+(\{[^}]+\})`)
var bcdDesc = regexp.MustCompile(`(?m)^description\s+(.+)$`)

// bootEntries parses `bcdedit /enum firmware`: each block has identifier + description.
func (w *Windows) bootEntries(ctx context.Context) ([]map[string]any, error) {
	out, err := w.run(ctx, "bcdedit", "/enum", "firmware")
	if err != nil {
		return nil, fmt.Errorf("bcdedit: %w (agent must run elevated)", err)
	}
	entries := []map[string]any{}
	for _, block := range strings.Split(strings.ReplaceAll(out, "\r\n", "\n"), "\n\n") {
		id := bcdIdent.FindStringSubmatch(block)
		if id == nil || id[1] == "{fwbootmgr}" {
			continue
		}
		title := id[1]
		if d := bcdDesc.FindStringSubmatch(block); d != nil {
			title = strings.TrimSpace(d[1])
		}
		entries = append(entries, map[string]any{"id": id[1], "title": title, "default": id[1] == "{bootmgr}"})
	}
	return entries, nil
}

func (w *Windows) setNextBoot(ctx context.Context, params map[string]any) Result {
	entry, ok := strParam(params, "entry")
	if !ok || !bcdGUID.MatchString(entry) {
		return Failf("set_next_boot: entry must be a {GUID} from get_boot_entries")
	}
	entries, err := w.bootEntries(ctx)
	if err != nil {
		return Fail(err)
	}
	for _, e := range entries {
		if e["id"] == entry {
			return w.exec(ctx, "bcdedit", "/set", "{fwbootmgr}", "bootsequence", entry)
		}
	}
	return Failf("set_next_boot: unknown entry '" + entry + "'")
}
