package adapter

import (
	"context"
	"strings"
	"testing"
)

func newWindows(calls *[]call, out map[string]string) *Windows {
	return NewWindows(fakeRunner(calls, out, nil), ApprovedCommands{"start-backend": {"cmd", "/c", "start-backend.bat"}})
}

func TestWindowsPowerActionsUseShutdownExe(t *testing.T) {
	var calls []call
	w := newWindows(&calls, nil)
	w.Run(context.Background(), "shutdown", nil)
	w.Run(context.Background(), "restart", nil)
	w.Run(context.Background(), "lock", nil)
	got := []string{joined(calls[0]), joined(calls[1]), joined(calls[2])}
	want := []string{"shutdown /s /t 5", "shutdown /r /t 5", "rundll32.exe user32.dll,LockWorkStation"}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("call %d: got %q want %q", i, got[i], want[i])
		}
	}
}

func TestWindowsRestartServiceValidatesName(t *testing.T) {
	var calls []call
	w := newWindows(&calls, nil)
	r := w.Run(context.Background(), "restart_service", map[string]any{"name": "Spooler"})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if joined(calls[0]) != "powershell -NoProfile -Command Restart-Service -Name 'Spooler' -Force" {
		t.Errorf("%q", joined(calls[0]))
	}
	if r := w.Run(context.Background(), "restart_service", map[string]any{"name": "x'; rm"}); r.Status != "failed" {
		t.Error("accepted injection")
	}
}

func TestWindowsBootEntriesParseBcdeditFirmware(t *testing.T) {
	bcd := `
Firmware Boot Manager
---------------------
identifier              {fwbootmgr}
displayorder            {bootmgr}
                        {a1b2c3d4-0000-1111-2222-333344445555}
timeout                 2

Windows Boot Manager
--------------------
identifier              {bootmgr}
device                  partition=\Device\HarddiskVolume1
description             Windows Boot Manager

Firmware Application (101fffff)
-------------------------------
identifier              {a1b2c3d4-0000-1111-2222-333344445555}
description             Linux Boot Manager
`
	var calls []call
	w := newWindows(&calls, map[string]string{"bcdedit": bcd})
	r := w.Run(context.Background(), "get_boot_entries", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	entries := r.Output["entries"].([]map[string]any)
	if len(entries) != 2 || entries[0]["id"] != "{bootmgr}" || entries[1]["title"] != "Linux Boot Manager" {
		t.Errorf("%+v", entries)
	}
	if !strings.Contains(joined(calls[0]), "/enum firmware") {
		t.Errorf("%q", joined(calls[0]))
	}
}

func TestWindowsSetNextBootUsesBootsequenceOnlyForKnownEntry(t *testing.T) {
	bcd := "identifier              {fwbootmgr}\n\nidentifier              {a1b2c3d4-0000-1111-2222-333344445555}\ndescription             Linux Boot Manager\n"
	var calls []call
	w := newWindows(&calls, map[string]string{"bcdedit": bcd})
	r := w.Run(context.Background(), "set_next_boot", map[string]any{"entry": "{a1b2c3d4-0000-1111-2222-333344445555}"})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if joined(calls[len(calls)-1]) != "bcdedit /set {fwbootmgr} bootsequence {a1b2c3d4-0000-1111-2222-333344445555}" {
		t.Errorf("%q", joined(calls[len(calls)-1]))
	}
	calls = nil
	r = w.Run(context.Background(), "set_next_boot", map[string]any{"entry": "{deadbeef-0000-1111-2222-333344445555}"})
	if r.Status != "failed" {
		t.Error("unknown GUID accepted")
	}
	for _, c := range calls {
		if c.name == "bcdedit" && len(c.args) > 0 && c.args[0] == "/set" {
			t.Error("unknown GUID reached bcdedit /set")
		}
	}
}

func TestWindowsLaunchAppAndApprovedCommand(t *testing.T) {
	var calls []call
	w := newWindows(&calls, nil)
	if r := w.Run(context.Background(), "launch_app", map[string]any{"app": "notepad"}); r.Status != "completed" || calls[0].name != "notepad" {
		t.Errorf("%+v %v", r, calls)
	}
	if r := w.Run(context.Background(), "run_approved_command", map[string]any{"command_id": "start-backend"}); r.Status != "completed" || calls[1].name != "cmd" {
		t.Errorf("%+v %v", r, calls)
	}
	if r := w.Run(context.Background(), "run_approved_command", map[string]any{"command_id": "nope"}); r.Status != "failed" {
		t.Error("ran unlisted command")
	}
}
