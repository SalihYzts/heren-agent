package adapter

import (
	"context"
	"errors"
	"testing"
)

const efiOut = `BootNext: 0001
BootCurrent: 0000
Timeout: 2 seconds
BootOrder: 0000,0001,0002
Boot0000* Linux Boot Manager	HD(1,GPT,aaaa)/File(\EFI\systemd\systemd-bootx64.efi)
Boot0001* Windows Boot Manager	HD(1,GPT,aaaa)/File(\EFI\Microsoft\Boot\bootmgfw.efi)
Boot0002  UEFI OS	HD(1,GPT,aaaa)/File(\EFI\BOOT\BOOTX64.EFI)
`

func TestBootEntriesFallBackToEfibootmgrWhenNoBootloaderTool(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"efibootmgr": efiOut},
		map[string]error{"bootctl": errors.New("no systemd-boot")})
	l.readFile = func(string) (string, error) { return "", errors.New("no grub.cfg") }
	r := l.Run(context.Background(), "get_boot_entries", nil)
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if r.Output["backend"] != "efi" {
		t.Errorf("backend %v", r.Output["backend"])
	}
	entries := r.Output["entries"].([]map[string]any)
	if len(entries) != 3 || entries[1]["id"] != "0001" || entries[1]["title"] != "Windows Boot Manager" || entries[0]["default"] != true {
		t.Errorf("%+v", entries)
	}
}

func TestSetNextBootUsesEfibootmgrBootNext(t *testing.T) {
	var calls []call
	l := newLinux(&calls, map[string]string{"efibootmgr": efiOut},
		map[string]error{"bootctl": errors.New("no systemd-boot")})
	l.readFile = func(string) (string, error) { return "", errors.New("no grub.cfg") }
	r := l.Run(context.Background(), "set_next_boot", map[string]any{"entry": "0001"})
	if r.Status != "completed" {
		t.Fatal(r.Error)
	}
	if last := joined(calls[len(calls)-1]); last != "efibootmgr -n 0001" {
		t.Errorf("%q", last)
	}
	calls = nil
	if r := l.Run(context.Background(), "set_next_boot", map[string]any{"entry": "0009"}); r.Status != "failed" {
		t.Error("unknown EFI entry accepted")
	}
	for _, c := range calls {
		if c.name == "efibootmgr" && len(c.args) > 0 && c.args[0] == "-n" {
			t.Error("unknown entry reached efibootmgr -n")
		}
	}
}
