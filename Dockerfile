# syntax=docker/dockerfile:1.7

FROM golang:1.22-bookworm AS builder
WORKDIR /src

COPY go.mod go.sum* ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o /out/ptz-service .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /out/ptz-service /usr/local/bin/ptz-service

ENV LISTEN=:8787 \
    PTZ_USER=admin \
    PTZ_PASS=admin \
    PTZ_SERIAL=/dev/ttyACM0 \
    PTZ_BAUD=115200 \
    PTZ_ZOOM_MAX=25 \
    PTZ_X_PER_STEP=10.0 \
    PTZ_Y_PER_STEP=10.0 \
    PTZ_FEED=200 \
    PTZ_ALLOW_RAW=false \
    CAM1_UPSTREAM=http://cam1:8080/?action=stream \
    CAM2_UPSTREAM=http://cam2:8080/?action=stream \
    CAM2_DEVICE=/dev/video2 \
    CAM2_CONTROL_DEVICE=/dev/video2 \
    CAM2_ZOOM_STEP=1

EXPOSE 8787
ENTRYPOINT ["ptz-service"]
