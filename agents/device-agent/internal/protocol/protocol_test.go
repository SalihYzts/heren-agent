package protocol

import (
	"encoding/json"
	"os"
	"testing"
)

type vector struct {
	SeedHex      string          `json:"seed_hex"`
	PublicKeyHex string          `json:"public_key_hex"`
	Envelope     json.RawMessage `json:"envelope"`
	Canonical    string          `json:"canonical"`
	Sig          string          `json:"sig"`
}

func loadVectors(t *testing.T) []vector {
	t.Helper()
	raw, err := os.ReadFile("../../../../packages/protocol/vectors/envelope_sign.json")
	if err != nil {
		t.Fatal(err)
	}
	var v []vector
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestCanonicalBytesMatchPython(t *testing.T) {
	for _, v := range loadVectors(t) {
		env, err := ParseEnvelope(v.Envelope)
		if err != nil {
			t.Fatal(err)
		}
		got, err := env.CanonicalBytes()
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != v.Canonical {
			t.Errorf("canonical mismatch\n got: %s\nwant: %s", got, v.Canonical)
		}
	}
}

func TestVerifyPythonSignatures(t *testing.T) {
	for _, v := range loadVectors(t) {
		env, _ := ParseEnvelope(v.Envelope)
		if err := Verify(env, v.PublicKeyHex); err != nil {
			t.Errorf("python-signed envelope %s failed verify: %v", env.ID, err)
		}
	}
}

func TestSignMatchesPythonSignature(t *testing.T) {
	// ed25519 is deterministic: same seed + same bytes ⇒ same signature.
	for _, v := range loadVectors(t) {
		kp, err := KeyPairFromSeedHex(v.SeedHex)
		if err != nil {
			t.Fatal(err)
		}
		if kp.PublicKeyHex() != v.PublicKeyHex {
			t.Fatalf("pubkey mismatch %s != %s", kp.PublicKeyHex(), v.PublicKeyHex)
		}
		env, _ := ParseEnvelope(v.Envelope)
		env.Sig = ""
		signed, err := Sign(env, kp)
		if err != nil {
			t.Fatal(err)
		}
		if signed.Sig != v.Sig {
			t.Errorf("sig mismatch for %s", env.ID)
		}
	}
}

func TestTamperedEnvelopeFailsVerify(t *testing.T) {
	v := loadVectors(t)[0]
	env, _ := ParseEnvelope(v.Envelope)
	env.Payload["cpu"] = 99
	if err := Verify(env, v.PublicKeyHex); err == nil {
		t.Error("tampered envelope verified")
	}
}

func TestNewEnvelopeFromGoValuesRoundTripsThroughPythonRules(t *testing.T) {
	// ints stay ints, integral floats keep ".0", non-ascii escaped, HTML not escaped
	env := NewEnvelope("dev-1", "heartbeat", map[string]any{
		"ram": 43, "cpu": 43.0, "load": 0.5, "name": "ünïcode <&>", "tab": "a\tb\x08",
	})
	env.ID, env.Nonce, env.TS = "msg_x", "n", 1.0
	got, _ := env.CanonicalBytes()
	want := `{"device_id":"dev-1","id":"msg_x","nonce":"n","payload":{"cpu":43.0,"load":0.5,"name":"\u00fcn\u00efcode <&>","ram":43,"tab":"a\tb\b"},"ts":1.0,"type":"heartbeat"}`
	if string(got) != want {
		t.Errorf("\n got: %s\nwant: %s", got, want)
	}
}

func TestWireJSONIsParseableAndReVerifiable(t *testing.T) {
	kp, _ := GenerateKeyPair()
	env := NewEnvelope("dev-1", "heartbeat", map[string]any{
		"cpu": 1.25, "n": 7,
		// shapes adapters actually produce:
		"entries": []map[string]any{{"id": "0001", "default": true}},
		"caps":    []string{"a", "b"},
		"nums":    []int{1, 2},
		"i64":     int64(9), "u": uint(3), "f32": float32(0.5),
	})
	signed, _ := Sign(env, kp)
	wire, err := signed.MarshalWire()
	if err != nil {
		t.Fatal(err)
	}
	back, err := ParseEnvelope(wire)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(back, kp.PublicKeyHex()); err != nil {
		t.Errorf("own wire envelope failed verify: %v\nwire=%s", err, wire)
	}
}
