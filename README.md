# EASPhub 计划审核

[下载 v2.2.0](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/tag/v2.2.0) · [操作手册](操作手册.md) · [服务器安装与升级](deploy/offline/部署说明.md)

欧洲仓库的备件补货计划审核。计划员可以直接导入本仓 V3 完整表，核对系统重算的库存区间和补货建议，带提醒提交复审。每版由一名复审员领取，可中途转交、逐行判断、退回修改，并导出终审核准的海运和空运量。

## 公司服务器升级

服务器需要 **Linux x86-64、Docker Engine、Docker Compose v2 和 flock**。离线包随附应用与 MySQL 8.4.8 镜像、Python 运行依赖、已编译的前端和三份 Excel 模板。公司同事用浏览器访问服务器的 `/apps/plan-review/`。

下载[服务器离线包](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.2.0/EASPhub-Plan-Review-v2.2.0-linux-amd64.tar.gz)和[校验清单](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.2.0/SHA256SUMS.txt)，放在同一个**新的程序目录**。从此目录执行以下命令。已有安装继续使用原业务数据目录；下例使用发行包的默认目录。

```sh
sha256sum --check --ignore-missing SHA256SUMS.txt
tar -xzf EASPhub-Plan-Review-v2.2.0-linux-amd64.tar.gz
cd EASPhub-Plan-Review-Server
sudo env STATE_DIR=/var/lib/easphub-plan-review sh server.sh install
sudo env STATE_DIR=/var/lib/easphub-plan-review sh server.sh status
```

原安装如自定义了 `STATE_DIR`，请将两条命令中的路径换成原值。首次安装会在指定目录创建独立数据库和初始管理员凭据。跨版本升级会暂停服务，先冷备原数据、附件、配置和密钥，再执行迁移。请预留备份空间，保留旧版程序目录用于恢复。默认冷备位置为 `/var/lib/easphub-plan-review.backups/`。HTTPS、域名和反向代理由服务器维护人员配置。

**升级后请核对两个业务设置。**

- 每人一个角色，可授权多个仓库。计划员负责提报，复审员另有规则、主数据、快照与复审权限，管理员再负责账号。旧多角色账号保留最高业务角色；只有旧技术或只读角色的账号停用、标为待分配。管理员可在「人员与权限」重新指定后启用。
- 新装以欧洲 V3 为默认。原安装按原有已发布标准继续审核。要在原仓启用 V3，由拥有完整适用范围的复审员或管理员在「审核标准」选择现有标准作为基础，新建 V3 草稿，试算后发布。历史计划保留原依据。

## Windows 工作电脑

下载 [Windows x64 离线包](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.2.0/PlanReview-v2.2.0-Windows-x64.zip)，完整解压到本机短路径，例如 `C:\Apps\PlanReview-2.2.0`。运行 `PlanReview-Windows-x64\Verify.cmd` 校验文件，再运行 `Start.cmd`。入口为 `http://127.0.0.1:3350/plan-review/`。首次初始化后运行 `Admin.cmd` 查看这台电脑生成的管理员凭据。

Windows 便携版同一 Windows 用户的数据目录为 `%LOCALAPPDATA%\EASPhubPlanReview\workspace`。更新时先关闭旧版，再启动新版；建议先备份该工作区。要处理公司服务器上的同一份计划，请使用公司的 HTTPS 入口。

## 模板与日常流程

- **完整计划模板（V3）**从所选计划下载，销量列跟随计划月份；海运和空运至少填一项。确认完整导入会替换草稿明细。系统按计划绑定的标准重算。
- **仅更新数量模板**按物料号合并。已有行只更新明确填写的一侧，填 0 才清零。模板七个表头都有批注。
- **V2 原表模板**用于兼容旧来源。三份模板都随程序提供。仓库公共快照可选，由复审员或管理员在「数据中心」维护。

## 从源码运行与测试

Windows 便携版与 Linux 公司服务器包包含运行环境。GitHub 的 Source code 压缩包用于开发。

后端依赖分别由 `requirements-lock.txt`、`requirements-linux.lock` 固定，前端使用 Node.js 24 和 `frontend/package-lock.json`。开发者可在仓库外创建 Python 3.12 虚拟环境，激活后从仓库根目录运行以下命令。

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements-test.lock
python -m pytest -p no:cacheprovider -q tests
python scripts/verify_operations.py
```

从位于普通开发目录的源码副本验证服务器前缀，可使用以下命令。测试使用独立的合成数据库。

```sh
(cd frontend && npm ci && APP_BASE_PATH=/apps/plan-review npm run build)
ADAPTATION_UI_DIR="$PWD/frontend/dist" python -m pytest -p no:cacheprovider -q tests_deployment
```

[Windows 构建说明](release/windows/BUILD.md) · [Linux 构建脚本](deploy/offline/build-server-release.sh)
