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
cp "$src/deploy/offline/offline.yml" "$src/deploy/compose.smtp.yml" "$src/deploy/compose.smtp-auth.yml" "$pkg/deploy/"
cp "$src/deploy/offline/server.sh" "$src/deploy/offline/fetch-accounts.sh" "$src/deploy/offline/部署说明.md" "$pkg/"
version=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([0-9][0-9.]*\)",*$/\1/p' "$src/frontend/package.json")
[ -n "$version" ] || { echo 'Cannot read package version.' >&2; exit 1; }
app="easphub-plan-review-app:$version"
db='easphub-plan-review-mysql:8.4.8'
mysql='mysql:8.4.8@sha256:4fc4bca5a26c5aa2246a92779d238bc2d34f0373e65dc083d7b635b02780dd3d'
docker build --platform linux/amd64 --provenance=false --label "org.opencontainers.image.version=$version" --label org.opencontainers.image.source=https://github.com/BilibiliSZdaomei/easphub-plan-review -t "$app" -f "$src/deploy/Dockerfile" "$src"
docker run --rm --pull=never --network none "$app" python -m pip check
docker run --rm --pull=never --network none "$app" python -c '
import json
import sys
from pathlib import Path
from zipfile import ZipFile
from backend.api import app
from backend.template_assets import dated_v3_template, WORKBOOK_TEMPLATES
ui=json.loads(Path("frontend/dist/app-build.json").read_text())
if (app.version,ui["version"],ui["base_path"],ui["review_model"]) != (sys.argv[1],sys.argv[1],"/apps/plan-review","V3"):
    raise SystemExit("Wrong application or interface build")
for template, _ in WORKBOOK_TEMPLATES.values():
    with ZipFile(template) as xlsx:
        if xlsx.testzip() or "xl/workbook.xml" not in xlsx.namelist():
            raise SystemExit(f"Invalid template: {template}")
assert dated_v3_template("2026-12")
assert ui["ui_revision"] == 22
from alembic.config import Config
from alembic.script import ScriptDirectory
assert ScriptDirectory.from_config(Config("alembic.ini")).get_current_head() == "0013"
assert Path("scripts/restore_accounts.py").is_file()
' "$version"
docker image inspect "$mysql" >/dev/null 2>&1 || docker pull --platform linux/amd64 "$mysql"
docker tag "$mysql" "$db"
docker save --platform linux/amd64 -o "$pkg/images.tar" "$app" "$db"
for image in "$app" "$db"; do
    layers=$(docker image inspect --format '{{range .RootFS.Layers}}{{println .}}{{end}}' "$image")
    digest=$(printf '%s\n' "$layers" | sha256sum | cut -d' ' -f1)
    printf '%s %s\n' "$image" "$digest"
done > "$pkg/IMAGE-IDS"
(cd "$pkg" && sha256sum IMAGE-IDS images.tar server.sh fetch-accounts.sh deploy/* 部署说明.md > SHA256SUMS)
(cd "$dest" && tar -czf "EASPhub-Plan-Review-v$version-linux-amd64.tar.gz" EASPhub-Plan-Review-Server)
