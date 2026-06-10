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
export INTERNAL_API_SECRET="$(openssl rand -hex 32)"
docker compose build
docker compose up -d
```

`INTERNAL_API_SECRET` 必须设置，三个角色用它保护内部 API。不要把真实 secret 提交到仓库。

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

管理员在后台扫码授权成功后，`web` 会保存 TV 授权 token 和从授权结果提取出的 Web Cookie，并更新 Cookie version。`danmaku-worker` 会通过内部 Cookie 接口检测版本变化并自动重连。

`scheduler` 会定时触发 `cookie-maintenance`。当 `SESSDATA` 距离过期不足默认 10 天时，`web` 使用已保存的 TV refresh token 刷新授权；刷新成功会替换 Web Cookie 并推进 Cookie version。refresh token 失效、B 站风控或上游接口异常时，系统会保留最后可用 Cookie，并在管理后台提示重新扫码授权。

TV `access_token`、`refresh_token`、`SESSDATA`、`bili_jct`、`buvid3` 都是敏感凭据，只能存在本地配置或数据库中，不要写入文档、日志或提交记录。

## 故障定位

```bash
docker compose logs --tail=200 web
docker compose logs --tail=200 danmaku-worker
docker compose logs --tail=200 scheduler
```

管理后台的 Cookie 状态接口会显示 TV 授权状态、Cookie 有效期、最近刷新/验证时间、角色状态、心跳年龄、最后错误、重试次数、Cookie version 和下一步建议。

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
