BINARY := aitokens-exporter
export CGO_ENABLED := 0

.PHONY: build test vet fmt install

build:
	go build -trimpath -o bin/$(BINARY) ./cmd/aitokens-exporter

test:
	go test ./... -race -count=1

vet:
	go vet ./...

fmt:
	gofmt -l .

install: build
	install -m 0755 bin/$(BINARY) $(HOME)/.local/bin/$(BINARY)
