计划审核 2.3.0 · Windows x64 离线版

首次使用
1. 从 GitHub Release 下载 PlanReview-v2.3.0-Windows-x64.zip，完整解压到本机可写的短路径目录，例如 C:\Apps\PlanReview。
2. 双击 Start.cmd。保留运行窗口，浏览器会打开 http://127.0.0.1:3350/plan-review/ 。
3. 同一 Windows 用户双击 Admin.cmd，复制初始密码，使用账号 admin 登录。可在个人菜单修改密码。
4. 在「管理 → 人员与权限」给每人选一个角色并分配仓库。复审员或管理员可在「管理 → 数据中心」下载 V3 模板及导入业务文件。新环境含十个仓库、欧洲通用 V3 标准和一个本机管理员，业务计划与快照从空库开始。

从已有账号配置首次启用
1. 准备管理员单独交付的加密账号包和配套密钥。解压程序后，在首次运行 Start.cmd 前打开该目录的 PowerShell。
2. 将以下两个示例路径替换为实际文件路径，然后运行
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restore-accounts.ps1 -Bundle "D:\Private\accounts.easphub" -KeyFile "D:\Private\accounts.key"
3. 看到恢复成功后双击 Start.cmd，使用原有账号和密码登录。已有数据的电脑先停止应用、备份 workspace；同一电脑常规升级直接共用原数据目录。

日常使用
• 启动时会校验解压后的程序文件，也可双击 Verify.cmd 单独检查。
• Windows 10/11 x64 自带的 Windows PowerShell 5.1 和浏览器即可使用。运行时、Python 依赖和网页均已随包提供，首次启动可离线。
• 退出时在启动窗口按 Ctrl+C，等服务停止。关闭浏览器标签后，后台服务仍会运行，直到停止启动窗口中的服务。
• 数据位于 %LOCALAPPDATA%\EASPhubPlanReview\workspace。关停后备份整个 workspace，包括数据库和 files 目录。更新时完整解压新版程序，再用同一 Windows 用户启动。初始密码卡使用当前 Windows 用户的 DPAPI 加密；Admin.cmd 显示的是首次生成的密码。
• 已有安装升级会保留既有业务标准。要按 V3 审核新计划，复审员或管理员可从「审核标准」新建 V3 草稿，试算并发布。原有多业务角色按最高角色合并，仅有旧职能或只读权限的账号需由管理员重新指定角色后启用。
• 若 3350 端口被其他程序使用，在解压目录打开命令提示符，先执行 set PLAN_REVIEW_PORT=3351，再执行 Start.cmd。
• 桌面版仅监听本机。部署供多人共同访问的系统，请使用同一版本的公司服务器发布包。
