# Brainstorm Summary

- Change: hard-cut-auth-runtime-watcher
- Date: 2026-06-10

## 确认的技术方案

已确认：采用 web/app 后端统一写业务数据库的运行边界。`danmaku-worker` 和 `scheduler` 不直接写业务 DB，而是通过 `INTERNAL_API_URL` + `INTERNAL_API_SECRET` 调用 web/app internal API。SQLite 仍是当前事实源，但它不是跨容器集成接口；未来换 PostgreSQL 时，worker/scheduler 不需要理解新 schema。

## 关键取舍与风险

- 取舍：比共享 SQLite 多一层 internal API，但换来清晰 ownership、未来 PostgreSQL 迁移路径、内部鉴权和审计边界。
- 风险：web/app internal API 不可用时，worker/scheduler 的状态写入会延迟。缓解：worker/scheduler 使用本地内存队列、bounded retry/backoff，并把 delivery failure 作为自身健康状态上报或记录到日志。
- 风险：scheduler 如果只通过 internal API，可能需要把原本本地函数调用拆成 internal job endpoints。缓解：先定义少量粗粒度 job endpoints，不做通用任务系统。

## 测试策略

- Internal API auth：缺 secret、错 secret、正确 secret。
- Danmaku ingestion：候选弹幕事件 POST 后，web/app 原子完成 auth success；重复事件只成功一次。
- Delivery retry：web/app 暂时失败时 worker 重试并记录 delivery failure。
- Scheduler：触发 guard/gift/session cleanup job 后由 web/app 写 DB，scheduler 不直接写业务表。
- Migration readiness：生产 runtime 检查 `danmaku-worker` 和 `scheduler` 不导入业务 DB writer 或直接 commit。

## Spec Patch

已回写 OpenSpec delta spec：internal API boundary、worker/scheduler 不直接写业务 DB、web/app 统一 business DB ownership、参考路径补全。当前无新增待回写 patch。
