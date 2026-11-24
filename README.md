# EASPhub 计划审核

[下载 v2.1.0](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/tag/v2.1.0) · [操作手册](操作手册.md)

用于欧洲仓库的备件补货计划。计划员可导入海运和空运数量、查看审核建议并提交复审。仓库数据按快照保存，审核建议按计划绑定的标准计算，每次提交和复审保留历史版本。

## Windows 工作电脑

下载 [Windows x64 离线包](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.1.0/PlanReview-v2.1.0-Windows-x64.zip)。完整解压到本机短路径目录，例如 `C:\Apps\PlanReview`，打开 PlanReview-Windows-x64 里的 **Start.cmd**。启动时自动核对包内文件，Python、运行依赖、两个 Excel 模板和编译好的界面均已提供。浏览器入口为 http://127.0.0.1:3350/plan-review/ 。

资料转移到内网后可用 **Verify.cmd** 单独检查解压结果。GitHub 的 Source code 压缩包供开发者使用。下载压缩包的 SHA-256 见 [SHA256SUMS.txt](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.1.0/SHA256SUMS.txt)。

首次启动后，用 **Admin.cmd** 查看本机生成的 admin 密码。登录后在「管理 → 人员与权限」为同事创建账号，分配计划员、复审员、数据维护等角色及授权仓库。本机业务数据存放在：

~~~text
%LOCALAPPDATA%\EASPhubPlanReview\workspace
~~~

## 公司服务器

使用已安装 Docker Engine 和 Docker Compose v2 的 **Linux x86-64** 服务器。下载 [公司服务器离线包](https://github.com/BilibiliSZdaomei/easphub-plan-review/releases/download/v2.1.0/EASPhub-Plan-Review-v2.1.0-linux-amd64.tar.gz)，按包内《部署说明.md》配置服务器、持久化存储和 HTTPS 入口。

~~~sh
tar -xzf EASPhub-Plan-Review-v2.1.0-linux-amd64.tar.gz
cd EASPhub-Plan-Review-Server
sudo sh server.sh install
sudo sh server.sh status
~~~

安装时会生成该服务器自己的初始管理员凭据。团队成员通过公司 HTTPS 地址的 `/apps/plan-review/` 访问同一套计划、快照和复审记录。Windows 版和服务器版各自保存数据；需要迁移已有业务记录时，请由管理员单独处理数据库、附件和备份。

## 导入首份快照

用有对应仓库权限的数据维护账号，进入「管理 → 数据中心」。下载 V2 模板，填写白色来源数据，蓝色列自动计算。选择本仓文件和库存截至日期，预览成功后发布。各仓库可以复用模板和默认标准，每份快照归属一个仓库。计划员也可以先建空草稿，之后再关联快照。

## 从源码运行和测试

- Python 后端源代码在 `backend/`，数据库版本在 `migrations/`。Windows 便携版和 Linux 镜像都带有运行依赖。
- 开发前端使用 Node.js 24、npm 和 `frontend/package-lock.json`。Windows 的源码启动器还需要本机 Python 3.12。准备好后，根目录的 `启动计划审核.cmd` 会按锁文件创建开发运行环境。
- Docker 镜像的 Python 运行依赖固定在 `requirements-linux.lock`，容器入口、MySQL 持久化和反向代理示例在 `deploy/`。

以下命令从仓库根目录执行。开发者可在仓库外创建一个 Python 3.12 虚拟环境，激活后运行：

~~~sh
python -m pip install --require-hashes --only-binary=:all: -r requirements-test.lock
python -m pytest -p no:cacheprovider -q tests
python scripts/verify_operations.py
~~~

在 Linux 上验证服务器部署契约时，先按服务器路径构建前端，再用单独的 Python 进程执行部署测试：

~~~sh
(cd frontend && npm ci && APP_BASE_PATH=/apps/plan-review npm run build)
ADAPTATION_UI_DIR="$PWD/frontend/dist" python -m pytest -p no:cacheprovider -q tests_deployment
~~~

业务测试使用临时数据库和合成物料。开发和验证产物可通过环境变量 `CODEX_ARTIFACT_ROOT` 指定到仓库外的绝对路径。
