package client

import (
	"context"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// A self-signed core (LAN TLS for phones) must be reachable when its cert is pinned via CAFile,
// and must be refused when it is not (never InsecureSkipVerify).
func TestPinnedCAFileTrustsSelfSignedCore(t *testing.T) {
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close(websocket.StatusNormalClosure, "")
		_, _, _ = c.Read(r.Context()) // enough to prove the TLS handshake passed
	}))
	srv.StartTLS()
	defer srv.Close()
	ca := t.TempDir() + "/cert.pem"
	if err := os.WriteFile(ca, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}), 0o600); err != nil {
		t.Fatal(err)
	}
	url := "wss" + strings.TrimPrefix(srv.URL, "https") + "/ws/agent"

	pinned, err := httpClientFor(Config{CoreURL: url, CAFile: ca})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if _, _, err := websocket.Dial(ctx, url, &websocket.DialOptions{HTTPClient: pinned}); err != nil {
		t.Fatalf("pinned CA should connect: %v", err)
	}
	plain, _ := httpClientFor(Config{CoreURL: url})
	if _, _, err := websocket.Dial(ctx, url, &websocket.DialOptions{HTTPClient: plain}); err == nil {
		t.Fatal("unpinned self-signed cert must be rejected")
	}
	if _, err := httpClientFor(Config{CoreURL: url, CAFile: t.TempDir() + "/missing.pem"}); err == nil {
		t.Fatal("missing CA file must be an error, not a silent fallback")
	}
}
