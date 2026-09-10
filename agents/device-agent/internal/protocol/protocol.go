// Package protocol implements the Nero wire envelope and ed25519 signing.
//
// CanonicalBytes must produce byte-identical output to Python's
// json.dumps(data, sort_keys=True, separators=(",", ":")) (ensure_ascii=True):
//   - object keys sorted, no whitespace
//   - non-ASCII escaped as \uXXXX (surrogate pairs above U+FFFF)
//   - integral floats rendered with ".0", other floats via repr (shortest round-trip)
//   - HTML characters NOT escaped
//   - true/false/null
package protocol

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
	"unicode/utf8"
)

// Envelope is the signed frame exchanged between core and agent.
type Envelope struct {
	ID       string         `json:"id"`
	TS       float64        `json:"ts"`
	Nonce    string         `json:"nonce"`
	DeviceID string         `json:"device_id"`
	Type     string         `json:"type"`
	Payload  map[string]any `json:"payload"`
	Sig      string         `json:"sig,omitempty"`
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// NewEnvelope creates an unsigned envelope with fresh id/nonce/timestamp.
func NewEnvelope(deviceID, typ string, payload map[string]any) *Envelope {
	if payload == nil {
		payload = map[string]any{}
	}
	return &Envelope{
		ID:       "msg_" + randomHex(9),
		TS:       float64(time.Now().UnixNano()) / 1e9,
		Nonce:    randomHex(16),
		DeviceID: deviceID,
		Type:     typ,
		Payload:  payload,
	}
}

// ParseEnvelope decodes wire JSON. Numbers inside payload are kept as json.Number
// so integers and floats are preserved for canonicalisation.
func ParseEnvelope(raw []byte) (*Envelope, error) {
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		return nil, err
	}
	env := &Envelope{}
	var ok bool
	if env.ID, ok = m["id"].(string); !ok {
		return nil, errors.New("envelope: missing id")
	}
	if env.Nonce, ok = m["nonce"].(string); !ok {
		return nil, errors.New("envelope: missing nonce")
	}
	if env.DeviceID, ok = m["device_id"].(string); !ok {
		return nil, errors.New("envelope: missing device_id")
	}
	if env.Type, ok = m["type"].(string); !ok {
		return nil, errors.New("envelope: missing type")
	}
	switch ts := m["ts"].(type) {
	case json.Number:
		f, err := ts.Float64()
		if err != nil {
			return nil, err
		}
		env.TS = f
	default:
		return nil, errors.New("envelope: missing ts")
	}
	if p, ok := m["payload"].(map[string]any); ok {
		env.Payload = p
	} else {
		env.Payload = map[string]any{}
	}
	if s, ok := m["sig"].(string); ok {
		env.Sig = s
	}
	return env, nil
}

// CanonicalBytes returns the bytes that are signed (everything except sig).
func (e *Envelope) CanonicalBytes() ([]byte, error) {
	data := map[string]any{
		"id": e.ID, "ts": e.TS, "nonce": e.Nonce, "device_id": e.DeviceID,
		"type": e.Type, "payload": e.Payload,
	}
	var sb strings.Builder
	if err := writeCanonical(&sb, data); err != nil {
		return nil, err
	}
	return []byte(sb.String()), nil
}

// MarshalWire encodes the envelope for sending. It uses the same canonical writer
// so the receiver re-derives identical bytes.
func (e *Envelope) MarshalWire() ([]byte, error) {
	data := map[string]any{
		"id": e.ID, "ts": e.TS, "nonce": e.Nonce, "device_id": e.DeviceID,
		"type": e.Type, "payload": e.Payload,
	}
	if e.Sig != "" {
		data["sig"] = e.Sig
	} else {
		data["sig"] = nil
	}
	var sb strings.Builder
	if err := writeCanonical(&sb, data); err != nil {
		return nil, err
	}
	return []byte(sb.String()), nil
}

func writeCanonical(sb *strings.Builder, v any) error {
	switch x := v.(type) {
	case nil:
		sb.WriteString("null")
	case bool:
		if x {
			sb.WriteString("true")
		} else {
			sb.WriteString("false")
		}
	case string:
		writeString(sb, x)
	case json.Number:
		s := x.String()
		if strings.ContainsAny(s, ".eE") {
			f, err := x.Float64()
			if err != nil {
				return err
			}
			sb.WriteString(pyFloat(f))
		} else {
			sb.WriteString(s)
		}
	case int:
		sb.WriteString(strconv.Itoa(x))
	case int64:
		sb.WriteString(strconv.FormatInt(x, 10))
	case int32:
		sb.WriteString(strconv.FormatInt(int64(x), 10))
	case uint64:
		sb.WriteString(strconv.FormatUint(x, 10))
	case float32:
		sb.WriteString(pyFloat(float64(x)))
	case float64:
		sb.WriteString(pyFloat(x))
	case []any:
		sb.WriteByte('[')
		for i, item := range x {
			if i > 0 {
				sb.WriteByte(',')
			}
			if err := writeCanonical(sb, item); err != nil {
				return err
			}
		}
		sb.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		sb.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				sb.WriteByte(',')
			}
			writeString(sb, k)
			sb.WriteByte(':')
			if err := writeCanonical(sb, x[k]); err != nil {
				return err
			}
		}
		sb.WriteByte('}')
	default:
		// Generic fallback for typed slices/maps/ints (e.g. []map[string]any, []string, uint).
		rv := reflect.ValueOf(v)
		switch rv.Kind() {
		case reflect.Slice, reflect.Array:
			arr := make([]any, rv.Len())
			for i := range arr {
				arr[i] = rv.Index(i).Interface()
			}
			return writeCanonical(sb, arr)
		case reflect.Map:
			if rv.Type().Key().Kind() != reflect.String {
				return fmt.Errorf("canonical: map key must be string, got %s", rv.Type().Key())
			}
			m := make(map[string]any, rv.Len())
			for _, k := range rv.MapKeys() {
				m[k.String()] = rv.MapIndex(k).Interface()
			}
			return writeCanonical(sb, m)
		case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
			sb.WriteString(strconv.FormatInt(rv.Int(), 10))
		case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
			sb.WriteString(strconv.FormatUint(rv.Uint(), 10))
		case reflect.Float32, reflect.Float64:
			sb.WriteString(pyFloat(rv.Float()))
		case reflect.Ptr, reflect.Interface:
			if rv.IsNil() {
				sb.WriteString("null")
				return nil
			}
			return writeCanonical(sb, rv.Elem().Interface())
		default:
			return fmt.Errorf("canonical: unsupported type %T", v)
		}
	}
	return nil
}

// pyFloat mimics Python's float repr: shortest round-trip, ".0" for integral values,
// exponent form for very large/small magnitudes.
func pyFloat(f float64) string {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return "null"
	}
	abs := math.Abs(f)
	if abs != 0 && (abs >= 1e16 || abs < 1e-4) {
		s := strconv.FormatFloat(f, 'e', -1, 64)
		// Python: 1e+16, 1.5e-05 — Go gives 1e+16, 1.5e-05 too.
		return s
	}
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(s, ".") {
		s += ".0"
	}
	return s
}

func writeString(sb *strings.Builder, s string) {
	sb.WriteByte('"')
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		switch {
		case r == '"':
			sb.WriteString(`\"`)
		case r == '\\':
			sb.WriteString(`\\`)
		case r == '\n':
			sb.WriteString(`\n`)
		case r == '\r':
			sb.WriteString(`\r`)
		case r == '\t':
			sb.WriteString(`\t`)
		case r == '\b':
			sb.WriteString(`\b`)
		case r == '\f':
			sb.WriteString(`\f`)
		case r < 0x20:
			fmt.Fprintf(sb, `\u%04x`, r)
		case r < 0x7f:
			sb.WriteByte(byte(r))
		case r <= 0xFFFF:
			fmt.Fprintf(sb, `\u%04x`, r)
		default:
			r1, r2 := utf16.EncodeRune(r)
			fmt.Fprintf(sb, `\u%04x\u%04x`, r1, r2)
		}
		i += size
	}
	sb.WriteByte('"')
}

// ----------------------------------------------------------------- keys

type KeyPair struct {
	priv ed25519.PrivateKey
}

func GenerateKeyPair() (*KeyPair, error) {
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	return &KeyPair{priv: priv}, nil
}

func KeyPairFromSeedHex(seedHex string) (*KeyPair, error) {
	seed, err := hex.DecodeString(seedHex)
	if err != nil {
		return nil, err
	}
	if len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("seed must be %d bytes", ed25519.SeedSize)
	}
	return &KeyPair{priv: ed25519.NewKeyFromSeed(seed)}, nil
}

func (k *KeyPair) SeedHex() string      { return hex.EncodeToString(k.priv.Seed()) }
func (k *KeyPair) PublicKeyHex() string { return hex.EncodeToString(k.priv.Public().(ed25519.PublicKey)) }

func Sign(e *Envelope, kp *KeyPair) (*Envelope, error) {
	b, err := e.CanonicalBytes()
	if err != nil {
		return nil, err
	}
	out := *e
	out.Sig = hex.EncodeToString(ed25519.Sign(kp.priv, b))
	return &out, nil
}

var ErrBadSignature = errors.New("bad signature")

func Verify(e *Envelope, publicKeyHex string) error {
	if e.Sig == "" {
		return errors.New("envelope is unsigned")
	}
	pub, err := hex.DecodeString(publicKeyHex)
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return errors.New("bad public key")
	}
	sig, err := hex.DecodeString(e.Sig)
	if err != nil {
		return ErrBadSignature
	}
	b, err := e.CanonicalBytes()
	if err != nil {
		return err
	}
	if !ed25519.Verify(ed25519.PublicKey(pub), b, sig) {
		return ErrBadSignature
	}
	return nil
}
