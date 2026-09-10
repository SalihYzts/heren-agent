GO ?= /usr/bin/go
PY := .venv/bin/python
AGENT := agents/device-agent

.PHONY: setup test test-core test-agent agent core dev-core clean

setup:
	uv venv --python 3.12 .venv
	VIRTUAL_ENV=$(CURDIR)/.venv uv pip install -e "apps/core[dev]"
	cd $(AGENT) && $(GO) mod download

test: test-core test-agent

test-core:
	cd apps/core && ../../$(PY) -m pytest -q -p no:cacheprovider

test-agent:
	cd $(AGENT) && $(GO) vet ./... && $(GO) test -race ./...

agent:
	cd $(AGENT) && CGO_ENABLED=0 $(GO) build -ldflags="-s -w" -o dist/heren-agent-linux-amd64 ./cmd/heren-agent
	cd $(AGENT) && CGO_ENABLED=0 GOARCH=arm64 $(GO) build -ldflags="-s -w" -o dist/heren-agent-linux-arm64 ./cmd/heren-agent
	cd $(AGENT) && CGO_ENABLED=0 GOOS=windows $(GO) build -ldflags="-s -w" -o dist/heren-agent-windows-amd64.exe ./cmd/heren-agent

dev-core:
	cd apps/core && HEREN_API_KEY=dev-key ../../$(PY) -m heren_core

vectors:
	cd apps/core && ../../$(PY) scripts/gen_vectors.py > ../../packages/protocol/vectors/envelope_sign.json

clean:
	rm -rf $(AGENT)/dist apps/core/.pytest_cache
