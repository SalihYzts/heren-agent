package protocol

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

// Go-signed envelope must verify in the Python core (the real consumer).
func TestPythonCoreVerifiesGoSignature(t *testing.T) {
	py := "../../../../.venv/bin/python"
	if _, err := os.Stat(py); err != nil {
		t.Skip("core venv not present")
	}
	kp, _ := GenerateKeyPair()
	env := NewEnvelope("dev-go", "heartbeat", map[string]any{
		"cpu": 12.5, "ram": 43, "name": "ünï <&> 😀", "list": []any{1, "a", 2.0, nil, true},
	})
	signed, _ := Sign(env, kp)
	wire, _ := signed.MarshalWire()
	script := `
import sys, json
sys.path.insert(0, "../../../../apps/core")
from heren_core.protocol import Envelope
from heren_core.security import verify
env = Envelope.model_validate_json(sys.stdin.read())
verify(env, sys.argv[1])
print("OK")`
	cmd := exec.Command(py, "-c", script, kp.PublicKeyHex())
	cmd.Stdin = strings.NewReader(string(wire))
	out, err := cmd.CombinedOutput()
	if err != nil || !strings.Contains(string(out), "OK") {
		t.Fatalf("python verify failed: %v\n%s\nwire=%s", err, out, wire)
	}
}
