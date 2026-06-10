# Brainstorm Summary

- Change: tv-token-cookie-auto-refresh
- Date: 2026-06-10

## 确认的技术方案

采用 Python 原生实现 Bilibili TV QR 登录与 refresh 协议。TV `access_token` 和 `refresh_token` 只作为续期凭据；运行时仍输出 Web Cookie 给现有 Bilibili Web/live API 使用。

首次管理员 TV QR 登录成功后，系统保存 refreshable authorization metadata、原始授权响应、提取出的 Web Cookie、`SESSDATA` 过期时间和 `cookie_version`。后续 `cookie-maintenance` 由 scheduler 触发、web 执行：当 Cookie 临期时使用 TV refresh token 获取新授权，提取新的 `cookie_info.cookies`，通过 `/x/web-interface/nav` 验证后才替换 runtime Cookie 并推进 `cookie_version`。`danmaku-worker` 继续通过现有 internal runtime Cookie endpoint 检测版本变化并重连。

## 关键取舍与风险

- 不引入 Node helper，除非 Python 复刻 TV 协议成本过高。这样部署复杂度最低。
- TV token 不直接替代 Web Cookie，避免破坏现有 live/Web API 调用。
- refresh 失败不覆盖最后一个可用 Cookie，只记录错误和管理员下一步。
- refresh token 失效、风控或 B 站接口变更时不能无感自愈，必须提示管理员重新扫码。
- scheduler 只触发，web 执行，保持 worker/scheduler 不直接写业务 DB 或配置。

## 测试策略

- Mocked tests 覆盖 TV QR 状态、refresh 成功/失败、Cookie 提取、过期判断、敏感字段脱敏。
- Runtime tests 覆盖 `cookie-maintenance` 执行闭环、`cookie_version` 增长、worker reload 判定。
- 有真实凭据时做最小实测：`/x/web-interface/nav`、`getDanmuInfo`、舰长列表接口。

## Spec Patch

无。当前 OpenSpec delta 已覆盖 TV token auth、passport QR 扩展、scheduler job 执行闭环。
