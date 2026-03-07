# syntax=docker/dockerfile:1.7

FROM golang:1.22-bookworm AS builder
WORKDIR /src

COPY go.mod ./
COPY . ./

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o /out/new-app-web .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /out/new-app-web /usr/local/bin/new-app-web
EXPOSE 8787
ENTRYPOINT ["new-app-web"]
