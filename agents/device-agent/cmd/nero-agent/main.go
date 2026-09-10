// nero-agent: device agent binary for Linux and Windows.
//
//	nero-agent --core ws://core:8700/ws/agent --pair 123456
//	nero-agent --config /etc/nero/agent.yaml
//
// Config file (YAML, all keys optional; flags override):
//
//	core_url: ws://127.0.0.1:8700/ws/agent
//	device_id: main-pc
//	name: MAIN PC
//	key_file: /var/lib/nero/agent.key
//	approved_commands:
//	  start-backend: ["systemctl", "--user", "start", "backend"]
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"

	"gopkg.in/yaml.v3"

	"nero/agent/internal/adapter"
	"nero/agent/internal/client"
	"nero/agent/internal/protocol"
)

type fileConfig struct {
	CoreURL          string              `yaml:"core_url"`
	DeviceID         string              `yaml:"device_id"`
	Name             string              `yaml:"name"`
	KeyFile          string              `yaml:"key_file"`
	ApprovedCommands map[string][]string `yaml:"approved_commands"`
	ActionTimeoutS   int                 `yaml:"action_timeout_s"`
}

func defaultKeyFile() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(os.Getenv("ProgramData"), "nero", "agent.key")
	}
	if os.Geteuid() == 0 {
		return "/var/lib/nero/agent.key"
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".nero", "agent.key")
}

func loadOrCreateKey(path string) (*protocol.KeyPair, error) {
	if b, err := os.ReadFile(path); err == nil {
		return protocol.KeyPairFromSeedHex(string(trim(b)))
	}
	kp, err := protocol.GenerateKeyPair()
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	if err := os.WriteFile(path, []byte(kp.SeedHex()), 0o600); err != nil {
		return nil, err
	}
	log.Printf("generated new device key at %s", path)
	return kp, nil
}

func trim(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == '\r' || b[len(b)-1] == ' ') {
		b = b[:len(b)-1]
	}
	return b
}

// execRunner runs a command without a shell; args are passed verbatim.
func execRunner(ctx context.Context, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("%w: %s", err, trim(out))
	}
	return string(out), nil
}

func main() {
	var (
		cfgPath = flag.String("config", "", "YAML config file")
		coreURL = flag.String("core", "", "core WebSocket URL (ws://host:8700/ws/agent)")
		devID   = flag.String("id", "", "device id (default: hostname)")
		name    = flag.String("name", "", "display name (default: hostname)")
		pair    = flag.String("pair", "", "one-time pairing code from the dashboard")
		keyFile = flag.String("key-file", "", "path to the device key")
	)
	flag.Parse()
	log.SetFlags(log.LstdFlags | log.Lmsgprefix)
	log.SetPrefix("nero-agent ")

	var fc fileConfig
	if *cfgPath != "" {
		b, err := os.ReadFile(*cfgPath)
		if err != nil {
			log.Fatalf("config: %v", err)
		}
		if err := yaml.Unmarshal(b, &fc); err != nil {
			log.Fatalf("config: %v", err)
		}
	}
	pick := func(flagV, fileV, def string) string {
		if flagV != "" {
			return flagV
		}
		if fileV != "" {
			return fileV
		}
		return def
	}
	host, _ := os.Hostname()
	cfg := client.Config{
		CoreURL:     pick(*coreURL, fc.CoreURL, "ws://127.0.0.1:8700/ws/agent"),
		DeviceID:    pick(*devID, fc.DeviceID, host),
		Name:        pick(*name, fc.Name, host),
		PairingCode: *pair,
	}
	if fc.ActionTimeoutS > 0 {
		cfg.ActionTimeout = time.Duration(fc.ActionTimeoutS) * time.Second
	}
	kp, err := loadOrCreateKey(pick(*keyFile, fc.KeyFile, defaultKeyFile()))
	if err != nil {
		log.Fatalf("key: %v", err)
	}

	var ad adapter.Adapter
	switch runtime.GOOS {
	case "linux":
		ad = adapter.NewLinux(execRunner, fc.ApprovedCommands)
	case "windows":
		ad = adapter.NewWindows(execRunner, fc.ApprovedCommands)
	default:
		log.Fatalf("unsupported platform %s", runtime.GOOS)
	}
	log.Printf("device %s (%s) key %s… → %s", cfg.DeviceID, ad.Platform(), kp.PublicKeyHex()[:12], cfg.CoreURL)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	a := client.New(cfg, kp, ad)
	a.Run(ctx)
	if err := a.FatalError(); err != nil {
		log.Fatal(err)
	}
}
