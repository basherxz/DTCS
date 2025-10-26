# Base image is provided by devcontainer "features" (Debian/Ubuntu)
# This file is here if you want to apt-get extra system packages.
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Optional system deps you might need
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
