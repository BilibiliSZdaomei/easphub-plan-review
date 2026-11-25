# 服务器 Agent 部署 v2.3.0

适用 Linux x86-64。服务器需已有 Docker Engine、Docker Compose v2 和 flock。以下命令在 Bash 中运行。

## 获取已含依赖的程序

选择一个新的私有工作目录，下载同一发行版的 Linux 包及校验清单。若服务器离线，可在联网电脑下载这两个文件后传入。

```bash
set -euo pipefail
umask 077
mkdir -p "$HOME/plan-review-releases"
cd "$(mktemp -d "$HOME/plan-review-releases/v2.3.0.XXXXXXXX")"
gh release download v2.3.0 --repo BilibiliSZdaomei/easphub-plan-review \
  --pattern 'EASPhub-Plan-Review-v2.3.0-linux-amd64.tar.gz' --pattern SHA256SUMS.txt
sha256sum --check --ignore-missing SHA256SUMS.txt
tar -xzf EASPhub-Plan-Review-v2.3.0-linux-amd64.tar.gz
cd EASPhub-Plan-Review-Server
```

## 选择安装方式

**已有正式实例。** 使用先前的状态目录，在维护窗口执行升级。状态目录示例为默认值。先核对路径与可用备份空间。

```bash
sudo env STATE_DIR=/var/lib/easphub-plan-review sh server.sh install
sudo env STATE_DIR=/var/lib/easphub-plan-review sh server.sh status
```

**新实例沿用已有登录。** 通过已授权的 GitHub CLI 和 OpenSSL，在本机产生一次性收件密钥。GitHub 身份需要本仓库的 Actions 读写权限；GitHub 细粒度令牌请仅授予此仓库，下载发行包另需 Contents 读权限。领取目录须尚不存在。离线服务器可由有权限的运维在联网电脑领取，再通过公司批准的渠道交付这两个文件。

```bash
config_dir="$HOME/plan-review-accounts-v2.3.0"
bash fetch-accounts.sh "$config_dir"
sudo sh server.sh install "$config_dir/accounts.easphub" "$config_dir/accounts.key"
sudo sh server.sh status
```

账号配置包含导出时的登录校验值、角色、授权仓库、启停状态、通知邮箱和头像设置。服务器上直接使用原密码登录。账号配置单独导入，业务计划、库存快照、复审记录和会话由原有业务数据目录或备份恢复。

已安装实例如确需补入账号，先备份，再执行 `sudo sh server.sh restore-accounts "$config_dir/accounts.easphub" "$config_dir/accounts.key"`。完全一致的账号会跳过。同名不同账号、设置冲突会整批停止，现有库不会被覆盖。请将配置包和解密文件按公司凭据管理制度保管。

## 验收

1. `server.sh status` 中数据库、Web 和 Worker 均应正常。在服务器上打开 `http://127.0.0.1:3350/apps/plan-review/`。通过既有 HTTPS 反向代理向员工提供服务。
2. 用已有账号和原密码登录，核对角色和授权仓库。管理员可进入 **管理 → 使用分析**，计划员和复审员看不到使用分析。
3. 需要节点邮件时填写公司 SMTP 主机、发件地址和认证设置，再提交一份测试计划核对实际收件。见[离线部署说明](部署说明.md)。

GitHub 只向手动触发的授权工作流提供账号 Secret。返回给服务器的解密文件按当次公钥包装，加密下载件一天后过期；后续部署可重新领取。公开下载程序即可离线运行，领取组织账号需单独授权。
