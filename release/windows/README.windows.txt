计划审核 2.0.0 · Windows x64 离线版

首次使用
1. 将 ZIP 完整解压到本机可读写的普通目录，例如 C:\Apps\PlanReview。
2. 双击 Start.cmd。保留运行窗口，浏览器会打开 http://127.0.0.1:3350/plan-review/ 。
3. 同一 Windows 用户双击 Admin.cmd，复制初始密码，使用账号 admin 登录。可在个人菜单修改密码。
4. 在「管理 → 人员与权限」建立计划员、复审员等岗位账号，分配仓库。数据维护人员可在「管理 → 数据中心」下载 V2 模板或导入业务文件。新环境含十个仓库、欧洲通用标准和一个本机管理员，业务计划与快照从空库开始。

日常使用
• Windows 10/11 x64 自带的 Windows PowerShell 5.1 和浏览器即可使用。运行时、Python 依赖和网页均已随包提供，首次启动可离线。
• 退出时在启动窗口按 Ctrl+C，等服务停止。关闭浏览器标签后，后台服务仍会运行，直到停止启动窗口中的服务。
• 数据位于 %LOCALAPPDATA%\EASPhubPlanReview\workspace。关停后备份整个 workspace，包括数据库和 files 目录。更新时完整解压新版程序，再用同一 Windows 用户启动。初始密码卡使用当前 Windows 用户的 DPAPI 加密；Admin.cmd 显示的是首次生成的密码。
• 若 3350 端口被其他程序使用，在解压目录打开命令提示符，先执行 set PLAN_REVIEW_PORT=3351，再执行 Start.cmd。
• 桌面版仅监听本机。部署供多人共同访问的系统，请使用同一版本的公司服务器发布包。
