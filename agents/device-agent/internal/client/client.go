// Package client is the agent's connection to nero-core: outbound WebSocket,
// hello/pairing, core-key pinning, signed envelopes, replay guard, heartbeat,
// reconnect with backoff, and action execution through an Adapter.
package client

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"nero/agent/internal/adapter"
	"nero/agent/internal/protocol"
)

type Config struct {
	CoreURL      string
	DeviceID     string
	Name         string
	PairingCode  string // used once; cleared after the first welcome
	ReconnectMin time.Duration
	ReconnectMax time.Duration
	ActionTimeout time.Duration
	ReplayWindow time.Duration
	ClockSkew    time.Duration
}

func (c *Config) defaults() {
	if c.ReconnectMin == 0 {
		c.ReconnectMin = time.Second
	}
	if c.ReconnectMax == 0 {
		c.ReconnectMax = 30 * time.Second
	}
	if c.ActionTimeout == 0 {
		c.ActionTimeout = 60 * time.Second
	}
	if c.ReplayWindow == 0 {
		c.ReplayWindow = 5 * time.Minute
	}
	if c.ClockSkew == 0 {
		c.ClockSkew = 30 * time.Second
	}
}

type Agent struct {
	cfg     Config
	kp      *protocol.KeyPair
	adapter adapter.Adapter

	mu         sync.Mutex
	connected  bool
	corePubKey string
	fatal      error
	seen       map[string]float64 // nonce → ts
}

func New(cfg Config, kp *protocol.KeyPair, ad adapter.Adapter) *Agent {
	cfg.defaults()
	return &Agent{cfg: cfg, kp: kp, adapter: ad, seen: map[string]float64{}}
}

func (a *Agent) Connected() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.connected
}

// FatalError is set when core rejected us permanently (key mismatch etc.) and
// retrying would be pointless — the operator has to re-pair.
func (a *Agent) FatalError() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.fatal
}

// Run connects and keeps reconnecting until ctx is cancelled or a fatal rejection occurs.
func (a *Agent) Run(ctx context.Context) {
	backoff := a.cfg.ReconnectMin
	for ctx.Err() == nil {
		err := a.session(ctx)
		if ctx.Err() != nil {
			return
		}
		var ce websocket.CloseError
		if errors.As(err, &ce) && ce.Code == 4003 && isPermanent(ce.Reason) {
			a.mu.Lock()
			a.fatal = errors.New("core rejected agent: " + ce.Reason)
			a.mu.Unlock()
			log.Printf("FATAL: %s — re-pair required", ce.Reason)
			return
		}
		if err != nil {
			log.Printf("connection lost: %v — retry in %s", err, backoff)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff *= 2
		if backoff > a.cfg.ReconnectMax {
			backoff = a.cfg.ReconnectMax
		}
	}
}

func isPermanent(reason string) bool {
	return strings.Contains(reason, "public key does not match") ||
		strings.Contains(reason, "pairing code required")
}

func (a *Agent) session(ctx context.Context) error {
	c, _, err := websocket.Dial(ctx, a.cfg.CoreURL, nil)
	if err != nil {
		return err
	}
	defer c.CloseNow()
	defer func() {
		a.mu.Lock()
		a.connected = false
		a.mu.Unlock()
	}()
	c.SetReadLimit(1 << 20)

	hello := map[string]any{
		"type": "hello", "device_id": a.cfg.DeviceID, "name": a.cfg.Name,
		"platform": a.adapter.Platform(), "public_key": a.kp.PublicKeyHex(),
		"capabilities": a.adapter.Capabilities(),
	}
	if a.cfg.PairingCode != "" {
		hello["pairing_code"] = a.cfg.PairingCode
	}
	if err := writeJSON(ctx, c, hello); err != nil {
		return err
	}
	_, raw, err := c.Read(ctx)
	if err != nil {
		return err
	}
	var welcome struct {
		Type       string  `json:"type"`
		CorePubKey string  `json:"core_public_key"`
		Interval   float64 `json:"heartbeat_interval_s"`
	}
	if err := json.Unmarshal(raw, &welcome); err != nil || welcome.Type != "welcome" {
		return errors.New("expected welcome, got: " + string(raw))
	}
	a.mu.Lock()
	a.corePubKey = welcome.CorePubKey
	a.connected = true
	a.cfg.PairingCode = "" // single use
	a.mu.Unlock()
	interval := time.Duration(welcome.Interval * float64(time.Second))
	if interval <= 0 {
		interval = 10 * time.Second
	}
	log.Printf("connected to core (heartbeat %s)", interval)

	sctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var wmu sync.Mutex
	send := func(typ string, payload map[string]any) error {
		env, err := protocol.Sign(protocol.NewEnvelope(a.cfg.DeviceID, typ, payload), a.kp)
		if err != nil {
			return err
		}
		wire, err := env.MarshalWire()
		if err != nil {
			return err
		}
		wmu.Lock()
		defer wmu.Unlock()
		return c.Write(sctx, websocket.MessageText, wire)
	}

	go func() {
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			metrics := a.adapter.Run(sctx, "get_metrics", nil)
			payload := map[string]any{}
			if metrics.Status == "completed" {
				payload = metrics.Output
			}
			if err := send("heartbeat", payload); err != nil {
				return
			}
			select {
			case <-sctx.Done():
				return
			case <-t.C:
			}
		}
	}()

	for {
		_, raw, err := c.Read(sctx)
		if err != nil {
			return err
		}
		a.handle(sctx, raw, send)
	}
}

func (a *Agent) handle(ctx context.Context, raw []byte, send func(string, map[string]any) error) {
	var probe struct {
		Type   string `json:"type"`
		Reason string `json:"reason"`
	}
	_ = json.Unmarshal(raw, &probe)
	if probe.Type == "error" {
		log.Printf("core error: %s", probe.Reason)
		return
	}
	env, err := protocol.ParseEnvelope(raw)
	if err != nil {
		log.Printf("malformed frame: %v", err)
		return
	}
	a.mu.Lock()
	pub := a.corePubKey
	a.mu.Unlock()
	if err := protocol.Verify(env, pub); err != nil {
		log.Printf("DROP frame %s: %v", env.ID, err)
		return
	}
	if !a.acceptNonce(env) {
		log.Printf("DROP replayed frame %s", env.ID)
		return
	}
	if env.Type != "action.request" {
		return
	}
	rid, _ := env.Payload["request_id"].(string)
	action, _ := env.Payload["action"].(string)
	params, _ := env.Payload["params"].(map[string]any)
	go func() {
		actx, cancel := context.WithTimeout(ctx, a.cfg.ActionTimeout)
		defer cancel()
		t0 := time.Now()
		res := a.adapter.Run(actx, action, params)
		payload := map[string]any{
			"request_id": rid, "status": res.Status,
			"duration_ms": int(time.Since(t0).Milliseconds()),
		}
		if res.Output != nil {
			payload["output"] = res.Output
		}
		if res.Error != "" {
			payload["error"] = res.Error
		}
		if err := send("action.result", payload); err != nil {
			log.Printf("failed to send result for %s: %v", rid, err)
			// Try a minimal failure frame so core does not have to wait for its timeout.
			_ = send("action.result", map[string]any{
				"request_id": rid, "status": "failed", "error": "agent could not encode result: " + err.Error(),
			})
		}
	}()
}

func (a *Agent) acceptNonce(env *protocol.Envelope) bool {
	now := float64(time.Now().UnixNano()) / 1e9
	win := a.cfg.ReplayWindow.Seconds()
	if env.TS < now-win || env.TS > now+a.cfg.ClockSkew.Seconds() {
		return false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	for n, ts := range a.seen {
		if ts < now-win {
			delete(a.seen, n)
		}
	}
	if _, dup := a.seen[env.Nonce]; dup {
		return false
	}
	a.seen[env.Nonce] = env.TS
	return true
}

func writeJSON(ctx context.Context, c *websocket.Conn, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return c.Write(ctx, websocket.MessageText, b)
}
