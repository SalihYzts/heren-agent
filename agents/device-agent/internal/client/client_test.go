package client

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"

	"nero/agent/internal/adapter"
	"nero/agent/internal/protocol"
)

// fakeCore is a minimal stand-in for nero-core's /ws/agent: it checks hello,
// sends welcome, verifies signatures and can push action.request frames.
type fakeCore struct {
	t          *testing.T
	kp         *protocol.KeyPair
	needCode   string
	knownKey   string
	mu         sync.Mutex
	hellos     []map[string]any
	received   []*protocol.Envelope
	conn       *websocket.Conn
	connected  chan struct{}
	rejectWith string
}

func newFakeCore(t *testing.T) *fakeCore {
	kp, _ := protocol.GenerateKeyPair()
	return &fakeCore{t: t, kp: kp, connected: make(chan struct{}, 10)}
}

func (f *fakeCore) handler(w http.ResponseWriter, r *http.Request) {
	c, err := websocket.Accept(w, r, nil)
	if err != nil {
		return
	}
	ctx := r.Context()
	_, raw, err := c.Read(ctx)
	if err != nil {
		return
	}
	var hello map[string]any
	_ = json.Unmarshal(raw, &hello)
	f.mu.Lock()
	f.hellos = append(f.hellos, hello)
	f.mu.Unlock()
	if f.rejectWith != "" {
		c.Close(4003, f.rejectWith)
		return
	}
	if f.needCode != "" && hello["pairing_code"] != f.needCode {
		c.Close(4003, "unknown device: valid pairing code required")
		return
	}
	if f.knownKey != "" && hello["public_key"] != f.knownKey {
		c.Close(4003, "public key does not match registered device key")
		return
	}
	f.needCode = "" // single use
	f.knownKey, _ = hello["public_key"].(string)
	welcome, _ := json.Marshal(map[string]any{"type": "welcome", "core_public_key": f.kp.PublicKeyHex(), "heartbeat_interval_s": 0.05})
	_ = c.Write(ctx, websocket.MessageText, welcome)
	f.mu.Lock()
	f.conn = c
	f.mu.Unlock()
	f.connected <- struct{}{}
	for {
		_, raw, err := c.Read(ctx)
		if err != nil {
			return
		}
		env, err := protocol.ParseEnvelope(raw)
		if err != nil {
			f.t.Errorf("bad envelope from agent: %v", err)
			continue
		}
		if err := protocol.Verify(env, f.knownKey); err != nil {
			f.t.Errorf("agent envelope failed verify: %v", err)
		}
		f.mu.Lock()
		f.received = append(f.received, env)
		f.mu.Unlock()
	}
}

func (f *fakeCore) send(env *protocol.Envelope) {
	f.mu.Lock()
	c := f.conn
	f.mu.Unlock()
	wire, _ := env.MarshalWire()
	_ = c.Write(context.Background(), websocket.MessageText, wire)
}

func (f *fakeCore) sendSigned(env *protocol.Envelope) {
	signed, _ := protocol.Sign(env, f.kp)
	f.send(signed)
}

func (f *fakeCore) waitFor(pred func(*protocol.Envelope) bool, d time.Duration) *protocol.Envelope {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		f.mu.Lock()
		for _, e := range f.received {
			if pred(e) {
				f.mu.Unlock()
				return e
			}
		}
		f.mu.Unlock()
		time.Sleep(5 * time.Millisecond)
	}
	return nil
}

type echoAdapter struct {
	mu    sync.Mutex
	calls []string
}

func (e *echoAdapter) Calls() []string {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]string(nil), e.calls...)
}

func (e *echoAdapter) Platform() string        { return "test" }
func (e *echoAdapter) Capabilities() []string  { return []string{"get_status"} }
func (e *echoAdapter) Run(_ context.Context, action string, p map[string]any) adapter.Result {
	if action == "get_metrics" { // heartbeat traffic, not under test
		return adapter.OK(map[string]any{"load1": 0.1})
	}
	e.mu.Lock()
	e.calls = append(e.calls, action)
	e.mu.Unlock()
	if action == "get_status" {
		return adapter.OK(map[string]any{"echo": p})
	}
	return adapter.Failf("nope")
}

func start(t *testing.T, f *fakeCore, code string) (*Agent, context.CancelFunc, *echoAdapter) {
	srv := httptest.NewServer(http.HandlerFunc(f.handler))
	t.Cleanup(srv.Close)
	kp, _ := protocol.GenerateKeyPair()
	ad := &echoAdapter{}
	a := New(Config{
		CoreURL: "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/agent",
		DeviceID: "dev-1", Name: "PC", PairingCode: code,
		ReconnectMin: 20 * time.Millisecond, ReconnectMax: 50 * time.Millisecond,
	}, kp, ad)
	ctx, cancel := context.WithCancel(context.Background())
	go a.Run(ctx)
	t.Cleanup(cancel)
	return a, cancel, ad
}

func TestAgentPairsWithCodeAndSendsHeartbeats(t *testing.T) {
	f := newFakeCore(t)
	f.needCode = "123456"
	a, _, _ := start(t, f, "123456")
	<-f.connected
	if f.hellos[0]["pairing_code"] != "123456" || f.hellos[0]["device_id"] != "dev-1" {
		t.Fatalf("bad hello %+v", f.hellos[0])
	}
	if hb := f.waitFor(func(e *protocol.Envelope) bool { return e.Type == "heartbeat" }, time.Second); hb == nil {
		t.Fatal("no heartbeat")
	}
	if !a.Connected() {
		t.Error("agent does not report connected")
	}
}

func TestAgentRunsSignedActionRequestAndRepliesWithResult(t *testing.T) {
	f := newFakeCore(t)
	_, _, ad := start(t, f, "")
	<-f.connected
	f.sendSigned(protocol.NewEnvelope("dev-1", "action.request", map[string]any{
		"request_id": "req_1", "action": "get_status", "params": map[string]any{"x": 1}}))
	res := f.waitFor(func(e *protocol.Envelope) bool { return e.Type == "action.result" }, time.Second)
	if res == nil {
		t.Fatal("no action.result")
	}
	if res.Payload["request_id"] != "req_1" || res.Payload["status"] != "completed" {
		t.Errorf("%+v", res.Payload)
	}
	if len(ad.Calls()) != 1 || ad.Calls()[0] != "get_status" {
		t.Errorf("adapter calls %v", ad.Calls())
	}
}

func TestAgentIgnoresRequestNotSignedByCore(t *testing.T) {
	f := newFakeCore(t)
	_, _, ad := start(t, f, "")
	<-f.connected
	other, _ := protocol.GenerateKeyPair()
	env := protocol.NewEnvelope("dev-1", "action.request", map[string]any{"request_id": "req_evil", "action": "get_status"})
	signed, _ := protocol.Sign(env, other)
	f.send(signed)
	unsigned := protocol.NewEnvelope("dev-1", "action.request", map[string]any{"request_id": "req_evil2", "action": "get_status"})
	f.send(unsigned)
	time.Sleep(100 * time.Millisecond)
	if len(ad.Calls()) != 0 {
		t.Errorf("adapter ran an unauthenticated request: %v", ad.Calls())
	}
	if res := f.waitFor(func(e *protocol.Envelope) bool { return e.Type == "action.result" }, 50*time.Millisecond); res != nil {
		t.Error("agent answered an unauthenticated request")
	}
}

func TestAgentRejectsReplayedRequest(t *testing.T) {
	f := newFakeCore(t)
	_, _, ad := start(t, f, "")
	<-f.connected
	env := protocol.NewEnvelope("dev-1", "action.request", map[string]any{"request_id": "req_r", "action": "get_status"})
	f.sendSigned(env)
	f.waitFor(func(e *protocol.Envelope) bool { return e.Type == "action.result" }, time.Second)
	f.sendSigned(env) // identical nonce
	time.Sleep(100 * time.Millisecond)
	if len(ad.Calls()) != 1 {
		t.Errorf("replayed request executed: %v", ad.Calls())
	}
}

func TestAgentReconnectsWithoutPairingCodeAfterDrop(t *testing.T) {
	f := newFakeCore(t)
	f.needCode = "111111"
	a, _, _ := start(t, f, "111111")
	<-f.connected
	f.mu.Lock()
	f.conn.Close(1012, "restart")
	f.mu.Unlock()
	select {
	case <-f.connected:
	case <-time.After(2 * time.Second):
		t.Fatal("agent did not reconnect")
	}
	f.mu.Lock()
	second := f.hellos[1]
	f.mu.Unlock()
	if _, has := second["pairing_code"]; has {
		t.Error("pairing code re-sent on reconnect")
	}
	if second["public_key"] != f.hellos[0]["public_key"] {
		t.Error("key changed between connects")
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && !a.Connected() {
		time.Sleep(5 * time.Millisecond)
	}
	if !a.Connected() {
		t.Error("not connected after reconnect")
	}
}

func TestAgentStopsRetryingOnKeyMismatchRejection(t *testing.T) {
	f := newFakeCore(t)
	f.rejectWith = "public key does not match registered device key"
	a, _, _ := start(t, f, "")
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && a.FatalError() == nil {
		time.Sleep(10 * time.Millisecond)
	}
	if a.FatalError() == nil {
		t.Fatal("agent kept retrying a permanent rejection")
	}
	f.mu.Lock()
	n := len(f.hellos)
	f.mu.Unlock()
	if n != 1 {
		t.Errorf("expected exactly one hello, got %d", n)
	}
}
