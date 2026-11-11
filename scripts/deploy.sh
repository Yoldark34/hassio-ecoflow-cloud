#!/usr/bin/env bash
# Deploy custom_components/ecoflow_cloud of this checkout to Home Assistant over ssh.
# Backs up the installed copy to /config/ecoflow_cloud_backups, runs `ha core check`, then restarts core.
# usage: scripts/deploy.sh [--no-restart]     host: $HA_SSH (default root@10.0.0.38)
set -euo pipefail
HA=${HA_SSH:-root@10.0.0.38}
root=$(cd "$(dirname "$0")/.." && pwd)
stamp=$(date +%Y%m%d_%H%M%S)
restart=1; [ "${1:-}" = "--no-restart" ] && restart=0

echo "Deploying $(git -C "$root" rev-parse --abbrev-ref HEAD) @ $(git -C "$root" log -1 --format='%h %s')"
if [ -n "$(git -C "$root" status --porcelain -- custom_components)" ]; then
  echo "Refusing: uncommitted changes under custom_components" >&2
  exit 1
fi
tgz=$(mktemp --suffix=.tgz)
trap 'rm -f "$tgz"' EXIT
tar -C "$root/custom_components" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyi' -czf "$tgz" ecoflow_cloud
scp -q "$tgz" "$HA:/tmp/ecoflow_cloud_deploy.tgz"

ssh "$HA" "set -e
  cd /config/custom_components
  # never keep the backup in custom_components: HA would load it as a second integration
  mkdir -p /config/ecoflow_cloud_backups
  [ -d ecoflow_cloud ] && cp -r ecoflow_cloud /config/ecoflow_cloud_backups/ecoflow_cloud.bak_$stamp
  rm -rf ecoflow_cloud
  tar xzf /tmp/ecoflow_cloud_deploy.tgz
  rm -f /tmp/ecoflow_cloud_deploy.tgz
  echo 'backup: /config/ecoflow_cloud_backups/ecoflow_cloud.bak_$stamp'
  grep '\"version\"' ecoflow_cloud/manifest.json
  ha core check"
if [ $restart = 1 ]; then
  ssh "$HA" "ha core restart"
  echo "Core restarted."
else
  echo "Deployed without restart."
fi
