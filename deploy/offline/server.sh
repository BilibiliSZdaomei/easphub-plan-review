#!/bin/sh
# Offline Linux/amd64 launcher for EASPhub Plan Review.
set -eu
umask 077
release_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
state_dir=${STATE_DIR:-/var/lib/easphub-plan-review}
action=${1:-install}
die() { printf '%s\n' "$*" >&2; exit 1; }
if [ "$(id -u)" != 0 ]; then die '请使用 sudo sh server.sh 运行。'; fi
case "$state_dir" in /|*/../*|*/..|*/./*|*//*|*[!A-Za-z0-9_./-]*|'') die 'STATE_DIR 须为专用绝对路径。';; /*) ;; *) die 'STATE_DIR 需要绝对路径。';; esac
case "$action" in install|start|stop|status|logs) ;; *) die '支持 install、start、stop、status、logs。';; esac
command -v docker >/dev/null && docker compose version >/dev/null || die '请先安装 Docker Engine 和 Compose v2。'
case "$(docker info --format '{{.OSType}}/{{.Architecture}}')" in linux/x86_64|linux/amd64) ;; *) die '需要 Linux x86_64 Docker Engine。';; esac
marker="$state_dir/.plan-review-offline"
config="$state_dir/app.env"
if [ "$action" = install ]; then
    mkdir -p -- "$state_dir"
    [ "$(realpath "$state_dir")" = "$state_dir" ] || die 'STATE_DIR 请使用实际路径。'
    if [ ! -f "$marker" ]; then
        [ -z "$(ls -A "$state_dir")" ] || die '这个目录已有其他文件，请指定空的专用 STATE_DIR。'
        chmod 700 "$state_dir"
        printf 'plan-review offline\n' >"$marker"
    fi
fi
[ -f "$marker" ] || die '此目录尚未安装。请先运行 install。'
exec 9>"$state_dir/.operation.lock"
flock 9
compose() {
    docker compose --project-name easphub-plan-review-company --env-file "$config" \
        -f "$release_dir/deploy/compose.company.yml" -f "$release_dir/deploy/offline.yml" "$@"
}
import_images() {
    [ -s "$release_dir/images.tar" ] || die '缺少 images.tar，请完整解压服务器包。'
    (cd "$release_dir" && sha256sum -c SHA256SUMS)
    docker load -i "$release_dir/images.tar"
    while read -r img expected; do
        layers=$(docker image inspect --format '{{range .RootFS.Layers}}{{println .}}{{end}}' "$img")
        actual=$(printf '%s\n' "$layers" | sha256sum | cut -d' ' -f1)
        [ "$actual" = "$expected" ] || die "镜像校验失败 $img"
    done < "$release_dir/IMAGE-IDS"
    app_image=$(awk '$1 ~ /^easphub-plan-review-app:[0-9]+\.[0-9]+\.[0-9]+$/ {print $1}' "$release_dir/IMAGE-IDS")
    [ -n "$app_image" ] && [ "$(printf '%s\n' "$app_image" | wc -l)" -eq 1 ] || die '包内缺少唯一的应用镜像版本。'
}
backup_before_upgrade() {
    backup_dir="${state_dir}.backups"
    [ ! -L "$backup_dir" ] || die '冷备目录须为实际路径。'
    mkdir -p "$backup_dir"
    [ "$(realpath "$backup_dir")" = "$backup_dir" ] || die '冷备目录须为实际路径。'
    chmod 700 "$backup_dir"
    # Archive the state directory and any externally configured bind mounts.
    set -- "${state_dir#/}"
    for field in APP_DATA_HOST_PATH MYSQL_DATA_HOST_PATH DATABASE_PASSWORD_FILE DATABASE_ROOT_PASSWORD_FILE MYSQL_CLIENT_FILE; do
        input=$(sed -n "s/^$field=//p" "$config")
        case "$input" in /|*/../*|*/..|''|*[!A-Za-z0-9_./-]*) die "冷备无法识别 $field 路径。";; /*) ;; *) die "冷备需要绝对路径 $field。";; esac
        [ -e "$input" ] && [ "$(realpath "$input")" = "$input" ] || die "冷备找不到实际路径 $field。"
        case "$backup_dir/" in "$input/"*) die '冷备目录位于业务数据路径内。';; esac
        case "$input" in "$state_dir"|"$state_dir"/*) ;; *) set -- "$@" "${input#/}";; esac
    done
    tmp=$(mktemp "$backup_dir/.pending.XXXXXXXX")
    running_services=$(compose ps --services --status running)
    compose stop web worker database
    if tar -C / -czf "$tmp" "$@" && tar -tzf "$tmp" >/dev/null; then
        backup="$backup_dir/pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ)-${tmp##*.}.tar.gz"
        mv "$tmp" "$backup"
        (cd "$backup_dir" && sha256sum "${backup##*/}" > "${backup##*/}.sha256")
        printf '升级前冷备已保存 %s\n' "$backup"
    else
        rm -f "$tmp"
        # Before migration the old configuration is still usable.
        if [ -n "$running_services" ]; then compose start $running_services; fi
        die '冷备失败；数据库未迁移。请核对备份空间和读取权限。'
    fi
}
random_secret() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; printf '\n'; }
create_secret() {
    f="$1"
    if [ ! -f "$f" ]; then random_secret >"$f.new"; chmod 444 "$f.new"; mv "$f.new" "$f"; fi
    [ -s "$f" ] || die '密钥为空，请核查运行目录。'
}
if [ "$action" = install ]; then
    import_images
    if [ ! -f "$config" ]; then
        proxy_network=${PROXY_NETWORK:-easphub-plan-review-proxy}
        port=${HTTP_PORT:-3350}
        case "$proxy_network" in ''|-*|*[!A-Za-z0-9_.-]*) die 'PROXY_NETWORK 名称无效。';; esac
        case "$port" in ''|*[!0-9]*) die 'HTTP_PORT 须为 1 至 65535。';; esac
        [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || die 'HTTP_PORT 须为 1 至 65535。'
        mkdir -p "$state_dir/app" "$state_dir/mysql" "$state_dir/secrets"
        chmod 700 "$state_dir/secrets"
        chown 10001:10001 "$state_dir/app"
        chown 999:999 "$state_dir/mysql"
        create_secret "$state_dir/secrets/database_password"
        create_secret "$state_dir/secrets/database_root_password"
        if [ ! -f "$state_dir/secrets/mysql_client" ]; then
            { printf '[client]\nuser=plan_review\nhost=127.0.0.1\nprotocol=tcp\npassword='; cat "$state_dir/secrets/database_password"; } > "$state_dir/secrets/mysql_client.new"
            chmod 444 "$state_dir/secrets/mysql_client.new"
            mv "$state_dir/secrets/mysql_client.new" "$state_dir/secrets/mysql_client"
        fi
        if [ ! -f "$state_dir/secrets/initial-admin-password" ]; then
            random_secret > "$state_dir/secrets/initial-admin-password.new"
            chmod 400 "$state_dir/secrets/initial-admin-password.new"
            mv "$state_dir/secrets/initial-admin-password.new" "$state_dir/secrets/initial-admin-password"
        fi
        cat > "$config.new" <<ENV
APP_IMAGE=$app_image
MYSQL_IMAGE=easphub-plan-review-mysql:8.4.8
TZ=Europe/Budapest
APP_DATA_HOST_PATH=$state_dir/app
MYSQL_DATA_HOST_PATH=$state_dir/mysql
DATABASE_PASSWORD_FILE=$state_dir/secrets/database_password
DATABASE_ROOT_PASSWORD_FILE=$state_dir/secrets/database_root_password
MYSQL_CLIENT_FILE=$state_dir/secrets/mysql_client
PROXY_NETWORK=$proxy_network
HTTP_PORT=$port
ENV
        mv "$config.new" "$config"
    fi
    proxy_network=$(sed -n 's/^PROXY_NETWORK=//p' "$config")
    docker network inspect "$proxy_network" >/dev/null 2>&1 || docker network create "$proxy_network" >/dev/null
    compose config --quiet
    if ! grep -Fxq "APP_IMAGE=$app_image" "$config"; then
        grep -q '^APP_IMAGE=' "$config" || die '现有配置缺少 APP_IMAGE。'
        backup_before_upgrade
        sed "s|^APP_IMAGE=.*$|APP_IMAGE=$app_image|" "$config" > "$config.new"
        mv "$config.new" "$config"
    fi
    compose up -d --wait --wait-timeout 300 database
    compose run --rm --no-deps -T migrate
    admin_input="$state_dir/secrets/initial-admin-password"
    [ -s "$admin_input" ] || admin_input=/dev/null
    compose run --rm --no-deps -T migrate python -c '
from pathlib import Path
import sys
from backend.db import transaction, User
from backend.markets import warehouse_config
from scripts.bootstrap import bootstrap
with transaction() as db:
    existing = db.query(User).first() is not None
if not existing:
    bootstrap("admin", "系统管理员", sys.stdin.readline().strip(), warehouse_config())
    print("初始管理员已建立。")
' < "$admin_input"
    compose up -d --wait --wait-timeout 300 database web worker
    printf '%s\n' '服务已就绪。首次登录账号 admin，请由管理员读取本机密码文件。' "$state_dir/secrets/initial-admin-password"
else
    [ -f "$config" ] || die '配置缺失，请先运行 install。'
    case "$action" in
        start) compose up -d --wait --wait-timeout 300 database web worker ;;
        stop) compose stop web worker database ;;
        status) compose ps ;;
        logs) compose logs --tail 80 web worker database ;;
    esac
fi
