#!/usr/bin/env bash
# Regenerate the *_pb2.py/.pyi of devices/internal/proto with protoc 32.0 (what mise's protoc task pins),
# downloading the official release once into ~/.cache. usage: scripts/protoc.sh [file.proto ...]
set -euo pipefail
ver=32.0
cache="$HOME/.cache/hassio-ecoflow-cloud/protoc-$ver"
if [ ! -x "$cache/bin/protoc" ]; then
  mkdir -p "$cache"
  zip="$cache/protoc.zip"
  curl -fsSL -o "$zip" "https://github.com/protocolbuffers/protobuf/releases/download/v$ver/protoc-$ver-linux-x86_64.zip"
  unzip -q -o "$zip" -d "$cache"
  rm -f "$zip"
fi
cd "$(dirname "$0")/../custom_components/ecoflow_cloud/devices/internal/proto"
if [ $# -eq 0 ]; then set -- *.proto; fi
"$cache/bin/protoc" --proto_path=. --python_out=. --pyi_out=. "$@"
"$cache/bin/protoc" --version
