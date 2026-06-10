## Why

弹幕鉴权和服务器稳定性问题的根因不是单点 bug，而是认证、弹幕监听、后台任务、部署健康检查都挤在同一进程里，并且关键状态散落在内存、线程和临时对象中。用户看到的结果是扫码重、鉴权飘、弹幕发了没反馈、管理员点重启也不知道是否真的恢复。

本变更允许一次性硬切：在基础技术栈保持 Python、Flask、SQLite、Docker Compose 的前提下，移除 Playwright 和老旧 `blivedm` 依赖，把认证与监听链路改成由 web/app 后端统一落库、其他运行角色通过 internal API 上报的可观测、可重启、可测试模型。

## What Changes

- **BREAKING**: 移除 Playwright 扫码登录运行依赖，改为 Bilibili Passport HTTP QR flow：生成二维码、轮询状态、保存 Cookie、校验 Cookie 完整性。
- **BREAKING**: 移除 `blivedm` 作为弹幕监听核心，改为项目内原生最小 Bilibili live WebSocket watcher，参考本机 `/Users/nowanti/Play/Projects/v-nexus-core-monorepo/services/watcher` 和 `/Users/nowanti/Play/Projects/bili-cli` 的已验证实现思路。
- **BREAKING**: Docker Compose 从单容器多职责改为多容器运行角色：`web`、`danmaku-worker`、`scheduler`。
- 将 `AuthSession`、二维码登录任务、Cookie 完整性、worker health/status 这类跨进程状态落到 SQLite，但 DB 写入 owner 归一到 web/app 后端服务层；`danmaku-worker` 和 `scheduler` 通过内部 API/webhook 上报事件、心跳和任务结果。
- 修复 Docker port、healthcheck、示例配置的运行契约不一致问题。
- 移除业务运行时内的 `git pull`/自动更新行为。
- 管理端状态从“线程是否活着”升级为“哪个角色健康、最近错误是什么、下一步建议是什么”。
- 为认证状态流、QR 登录、原生 watcher 协议解析/重连、worker 启停、Docker 配置一致性补充回归测试。
- 保持一个合并 change，不拆多个 OpenSpec changes：这是一次有意硬切，认证状态、监听核心、运行角色和部署契约互相依赖，拆开会保留旧债并延长用户可见不稳定期。

## Capabilities

### New Capabilities

- `passport-qr-login`: 定义无浏览器依赖的 Bilibili QR 登录、Cookie 校验和管理员反馈。
- `database-backed-auth`: 定义弹幕鉴权状态、登录任务、Cookie/worker 状态以 web/app 后端管理的数据库为事实源。
- `native-danmaku-watcher`: 定义原生 Bilibili 弹幕监听、协议处理、重连、事件归一化和内部 webhook 上报。
- `split-runtime-roles`: 定义 Web、弹幕 worker、scheduler 多容器职责、内部 API 边界、健康检查和部署契约。

### Modified Capabilities

- None. 当前仓库没有已归档主 specs，本变更新增能力规格。

## Impact

- Affected code: `app.py`, `routes.py`, `services/auth_service.py`, `services/cookie_service.py`, `services/danmaku_listener.py`, new watcher/runtime modules, scheduler setup, DB models/init, admin status routes/templates.
- Affected operations: local manual run, Docker Compose deployment, admin Cookie login, auth page polling, listener restart/status, periodic guard/gift/session cleanup.
- Dependencies: remove Playwright runtime/browser dependency and `blivedm`; add only small protocol/HTTP dependencies if not already present. Do not introduce Redis, Celery, Postgres, or a new language runtime in this change.
- Data: SQLite remains the source of truth for this change, but only web/app backend services write business state directly. New tables/columns are acceptable for QR login sessions, cookie integrity metadata, auth attempts, scheduler jobs, and worker status. The worker/scheduler boundary must remain HTTP/internal-API based so future PostgreSQL migration does not require rewriting the watcher.
- User impact: users should no longer experience “弹幕发了但系统没认”； admins should see actionable status and can restart only the failed runtime role instead of treating the whole server as crashed.
