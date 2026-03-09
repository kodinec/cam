# syntax=docker/dockerfile:1.7

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        intel-media-va-driver \
        i965-va-driver \
        mesa-va-drivers \
        uhubctl \
        vainfo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENTRYPOINT ["/bin/sh", "/scripts/cam1_publisher.sh"]
