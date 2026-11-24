#!/bin/sh
# Run from an external workspace. Output paths must be outside the repository.
set -eu
src=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd -P)
dest=${1:?usage: sh deploy/offline/build-server-release.sh /absolute/empty/output}
mkdir -p "$dest"
dest=$(CDPATH='' cd "$dest" && pwd -P)
case "$dest" in "$src"|"$src"/*) echo 'Choose an output outside the source tree.' >&2; exit 1;; esac
[ -z "$(ls -A "$dest")" ] || { echo 'Output must be empty.' >&2; exit 1; }
pkg="$dest/EASPhub-Plan-Review-Server"
mkdir -p "$pkg/deploy"
cp "$src/deploy/compose.yml" "$src/deploy/compose.company.yml" "$src/deploy/nginx-location.company.conf" "$pkg/deploy/"
cp "$src/deploy/offline/offline.yml" "$pkg/deploy/"
cp "$src/deploy/offline/server.sh" "$src/deploy/offline/部署说明.md" "$pkg/"
app='easphub-plan-review-app:2.1.0'
db='easphub-plan-review-mysql:8.4.8'
mysql='mysql:8.4.8@sha256:4fc4bca5a26c5aa2246a92779d238bc2d34f0373e65dc083d7b635b02780dd3d'
docker build --platform linux/amd64 --provenance=false --label org.opencontainers.image.version=2.1.0 --label org.opencontainers.image.source=https://github.com/BilibiliSZdaomei/easphub-plan-review -t "$app" -f "$src/deploy/Dockerfile" "$src"
docker run --rm --network none "$app" python -c '
import json
from pathlib import Path
from zipfile import ZipFile
from backend.api import app
ui=json.loads(Path("frontend/dist/app-build.json").read_text())
if (app.version,ui["version"],ui["base_path"]) != ("2.1.0","2.1.0","/apps/plan-review"):
    raise SystemExit("Wrong application or interface build")
for template in ("plan-review-v2.xlsx", "replenishment-plan.xlsx"):
    with ZipFile(Path("backend/templates") / template) as xlsx:
        if xlsx.testzip() or "xl/workbook.xml" not in xlsx.namelist():
            raise SystemExit(f"Invalid template: {template}")
'
docker pull --platform linux/amd64 "$mysql"
docker tag "$mysql" "$db"
docker save --platform linux/amd64 -o "$pkg/images.tar" "$app" "$db"
for image in "$app" "$db"; do
    layers=$(docker image inspect --format '{{range .RootFS.Layers}}{{println .}}{{end}}' "$image")
    digest=$(printf '%s\n' "$layers" | sha256sum | cut -d' ' -f1)
    printf '%s %s\n' "$image" "$digest"
done > "$pkg/IMAGE-IDS"
(cd "$pkg" && sha256sum IMAGE-IDS images.tar server.sh deploy/* 部署说明.md > SHA256SUMS)
(cd "$dest" && tar -czf EASPhub-Plan-Review-v2.1.0-linux-amd64.tar.gz EASPhub-Plan-Review-Server)
