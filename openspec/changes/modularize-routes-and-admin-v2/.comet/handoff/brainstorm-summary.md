# Brainstorm Summary

- Change: modularize-routes-and-admin-v2
- Date: 2026-06-10

## 确认的技术方案

将单体 `routes.py` 拆成 `route_handlers/` 包，保留 `routes.py` 作为稳定入口。`register_routes(app)`、三类 Blueprint、现有 endpoint 名称和 URL 行为保持兼容。

## 关键取舍与风险

使用 `route_handlers/` 而不是 `routes/`，避免与现有 `routes.py` 产生导入冲突。主要风险是 endpoint 漂移、管理员保护丢失、内部 API 响应变化和 Docker 镜像遗漏新目录；分别用路由库存测试、保护测试、内部 API 测试和 Dockerfile 复制规则覆盖。

## 测试策略

先固定路由库存，再验证 URL generation、管理员保护、Cookie 管理保护、内部 API 鉴权拒绝，并复跑 auth、QR login、internal API、runtime Cookie 相关测试。

## Spec Patch

无。
