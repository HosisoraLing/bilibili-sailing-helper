# Docker 部署说明

## 运行角色

当前 Docker Compose 使用三个运行角色：

- `web`：对外提供页面、管理后台和内部 API，拥有 SQLite 业务写入。
- `danmaku-worker`：连接 B 站直播弹幕，读取 web 提供的运行时 Cookie，通过内部 API 上报鉴权事件。
- `scheduler`：定时触发内部任务，通过内部 API 通知 web，不直接写数据库。

`web` 对外端口固定为 `7111`。

## 启动

```bash
cp settings.json.example settings.json
cp .env.example .env
# 编辑 .env，把 INTERNAL_API_SECRET 固定为一次性生成的强随机值
python -m db.init_db
docker compose build
docker compose up -d
```

`INTERNAL_API_SECRET` 必须写入 `.env`，三个角色用它保护内部 API。不要每次 shell 临时 `export` 新值；一旦三个角色使用的 secret 不一致，worker/scheduler 会无法调用 web 内部 API。不要把真实 secret 提交到仓库。

## 从旧版升级

从上游旧版单进程部署升级到当前三角色运行时前，先停服务并显式迁移 SQLite。服务启动不会自动迁移已有数据库。

```bash
docker compose down
python scripts/migrate_legacy_db.py --db data/app.db --settings settings.json
docker compose up -d
```

迁移脚本会先把数据库备份到 `backups/`，再补齐新版运行时表和字段，并迁移旧版 `users.is_admin`。旧 `settings.json` 中已有的 B 站 Cookie 不会导入 DB；升级后请在后台重新 Web 扫码授权，避免旧 Cookie 与 Web refresh token 错配。预演可用：

```bash
python scripts/migrate_legacy_db.py --db data/app.db --settings settings.json --dry-run
```

## 镜像自动构建

GitHub Actions 会在以下场景构建多架构镜像：

- Pull Request：只构建验证，不推送镜像。
- `main` 分支 push：推送到 `ghcr.io/<owner>/<repo>`，包含分支名、`latest` 和 `sha-*` 标签。
- `v*` tag push：推送到 `ghcr.io/<owner>/<repo>`，包含 semver 标签和 `sha-*` 标签。

默认发布到 GHCR，不需要额外配置。镜像包写入权限来自 GitHub 内置的 `GITHUB_TOKEN`。

如需同步推送一份到阿里云容器镜像服务，在仓库配置中补齐：

- Repository variables:
  - `ALIYUN_REGISTRY`，例如 `registry.cn-hangzhou.aliyuncs.com`
  - `ALIYUN_NAMESPACE`，例如 `your-namespace`
- Repository secrets:
  - `ALIYUN_USERNAME`
  - `ALIYUN_PASSWORD`

四项配置都存在时，workflow 会把同一组标签额外推送到：

```text
${ALIYUN_REGISTRY}/${ALIYUN_NAMESPACE}/bilibili-sailing-helper:<tag>
```

## 常用命令

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f danmaku-worker
docker compose logs -f scheduler
docker compose restart web
docker compose restart danmaku-worker
docker compose restart scheduler
docker compose down
```

如果只有弹幕鉴权异常，优先重启 `danmaku-worker`。如果只有定时任务异常，优先重启 `scheduler`。

## 数据与配置

- `./settings.json` 挂载到 `/app/settings.json`。
- `./data` 挂载到 `web` 的 `/app/data`，SQLite 数据库只由 `web` 写入。
- `./logs` 挂载到三个角色的 `/app/logs`。
- `danmaku-worker` 和 `scheduler` 不挂载 `./data`。

## SQLite 备份

升级或执行结构性变更前先备份：

```bash
docker compose stop web danmaku-worker scheduler
mkdir -p backups
cp -a data backups/data-$(date +%Y%m%d-%H%M%S)
docker compose up -d
```

## Cookie 更新

管理员在后台使用 Web 扫码授权成功后，`web` 会把完整 Web `cookie_header` 和同源 refresh token 保存到 DB，并更新 Cookie version。`danmaku-worker` 会通过内部 Cookie 接口检测版本变化并自动重连。

运行时 Cookie 只以 DB `cookie_metadata.cookie_header` 为准；`settings.json` 只写出 `bilibili_auth_mirror` 作为本地审计镜像，不再作为读取来源。

`scheduler` 会定时触发 `cookie-maintenance`。`web` 先调用 B 站 Web Cookie 检查接口；无需刷新时保持现有 Cookie 不变，需要刷新时使用 Web refresh token 获取新的 Web Cookie，确认旧 token 失效，并推进 Cookie version。refresh token 失效、B 站风控或上游接口异常时，系统会保留最后可用 Cookie，并在管理后台提示重新扫码授权。

Web refresh token、`SESSDATA`、`bili_jct`、`buvid3` 都是敏感凭据，只能存在本地数据库或本地镜像配置中，不要写入文档、日志或提交记录。

## 故障定位

```bash
docker compose logs --tail=200 web
docker compose logs --tail=200 danmaku-worker
docker compose logs --tail=200 scheduler
```

管理后台的 Cookie 状态接口会显示 Web QR 授权状态、最近验证时间、角色状态、心跳年龄、最后错误、重试次数、Cookie version 和下一步建议。

## SSL

如需启用 SSL，在 `settings.json` 中配置证书路径，并把证书目录挂载到 `web` 容器：

```json
{
  "ssl": {
    "enabled": true,
    "cert_file": "ssl/cert.pem",
    "key_file": "ssl/key.pem",
    "port": 7112
  }
}
```
