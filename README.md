# B站舰礼地址收集助手

B站舰长/陪伴榜用户地址收集与舰礼履约系统。项目面向主播运营场景：用户通过直播间弹幕完成身份验证，自助填写收货地址；管理员在后台同步舰长名单、管理地址、统计舰礼资格、维护 B 站授权状态。

当前版本已经拆成三个运行角色：

- `web`：对外提供页面、管理后台、SocketIO 和内部 API；只有它直接写 SQLite。
- `danmaku-worker`：连接 B 站直播弹幕 WebSocket，监听验证码弹幕，通过内部 API 投递鉴权事件。
- `scheduler`：定时触发舰长同步、舰礼统计和鉴权会话清理，通过内部 API 请求 `web` 执行。

这种拆分的目标是让用户侧体验更稳：页面服务、弹幕连接、定时任务互相隔离，某个后台角色异常时可以单独重启，并且管理后台能给出下一步建议。

## 核心功能

- 弹幕鉴权：用户在直播间发送页面验证码完成注册、登录或重置密码。
- 地址收集：舰长/陪伴榜用户自助填写和更新收货信息。
- 管理后台：地址、舰长名单、用户权限、舰礼资格、CSV 导入导出。
- 舰长同步：从 B 站直播接口同步舰长/陪伴榜数据，保留是否在舰、舰长等级和陪伴天数。
- 舰礼统计：按月份计算符合资格的舰长礼物记录，并支持领取状态管理。
- B 站授权维护：后台支持 Web 扫码授权，保存 Web Cookie 和 refresh token；scheduler 会在 B 站要求刷新时自动轮换 Cookie。
- 运行态可观测：后台展示 Cookie 状态、Worker/Scheduler 心跳、Cookie version、最近错误和下一步操作建议。
- Docker 部署：Compose 默认启动 `web`、`danmaku-worker`、`scheduler` 三个角色。

## 快速开始

### Docker 部署

```bash
git clone https://github.com/HosisoraLing/bilibili-sailing-helper.git
cd bilibili-sailing-helper

cp settings.json.example settings.json
cp .env.example .env
# 编辑 .env，把 INTERNAL_API_SECRET 固定为一次性生成的强随机值

docker compose build
docker compose up -d
```

后续更新可使用部署脚本：

```bash
./deploy.sh                  # git pull + 增量构建 + 重启所有服务
./deploy.sh --no-update      # 跳过 git pull，只构建 + 重启
./deploy.sh --web            # 只重建并重启 web
./deploy.sh --restart-only   # 只重启服务，不重建镜像
```

完整参数：

| 参数 | 说明 |
|------|------|
| `--web` | 只操作 web 服务 |
| `--danmaku` | 只操作 danmaku-worker 服务 |
| `--scheduler` | 只操作 scheduler 服务 |
| `--no-cache` | 全量重建（requirements.txt 变更时使用） |
| `--pull` | 拉取最新基础镜像 |
| `--build-only` | 只构建镜像，不重启服务 |
| `--restart-only` | 只重启服务，不重建镜像 |
| `--cn-mirror` | 使用国内镜像源（阿里云 apt/pip） |
| `--no-update` | 跳过 git pull（默认会拉取更新） |
| `--logs` | 部署后跟踪日志 |
| `--status` | 只显示服务状态，不做任何操作 |

参数可组合使用，例如：

```bash
./deploy.sh --web --cn-mirror --logs    # 用国内镜像构建 web 并跟踪日志
./deploy.sh --no-cache --pull           # 全量重建并拉取最新基础镜像
```

访问：

- 首页：`http://localhost:7111/`
- 管理后台：`http://localhost:7111/admin/panel`
- 鉴权页面：`http://localhost:7111/auth?uid=<B站UID>`

首次启动前需要编辑 `settings.json`，至少填写主播房间信息、管理员 UID 和密钥。管理员登录后台后，优先使用 Web 扫码授权完成 B 站 Cookie 初始化。

新安装如果还没有数据库，先显式初始化一次：

```bash
python -m db.init_db
```

从上游旧版升级到当前重构版时，不要靠服务启动自动改库，先停服务并运行迁移脚本：

```bash
docker compose down
python scripts/migrate_legacy_db.py --db data/app.db --settings settings.json
docker compose up -d
```

迁移脚本会先备份 SQLite 到 `backups/`，再补齐新版运行时表和字段，并迁移旧版管理员标记。旧 `settings.json` 中已有的 B 站 Cookie 不会导入 DB；升级后请在后台重新 Web 扫码授权，避免旧 Cookie 与 Web refresh token 错配。预演可用：

```bash
python scripts/migrate_legacy_db.py --db data/app.db --settings settings.json --dry-run
```

### 本地开发运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp settings.json.example settings.json
cp .env.example .env
# 编辑 .env，把 INTERNAL_API_SECRET 固定为一次性生成的强随机值
set -a
source .env
set +a

python -m db.init_db
python -m runtime.web
```

如果要在本地同时验证完整运行时，再开两个终端：

```bash
export INTERNAL_API_URL=http://127.0.0.1:7111
source .env
python -m runtime.danmaku_worker
```

```bash
export INTERNAL_API_URL=http://127.0.0.1:7111
source .env
python -m runtime.scheduler
```

## 配置

`settings.json` 示例：

```json
{
  "anchor": {
    "nickname": "主播昵称",
    "room_id": 123456,
    "ruid": 789012
  },
  "bilibili_auth_mirror": {
    "source": "db.cookie_metadata",
    "role": "admin",
    "status": "missing",
    "cookie_version": 0,
    "cookie_header": "",
    "has_web_refresh_token": false,
    "masked_uid": "",
    "updated_at": ""
  },
  "database": {
    "url": "sqlite:///data/app.db"
  },
  "flask": {
    "secret_key": "replace-this-secret",
    "debug": false,
    "host": "0.0.0.0",
    "port": 7111
  },
  "ssl": {
    "enabled": false,
    "cert_file": "",
    "key_file": "",
    "port": 7112
  },
  "admin": {
    "uids": ["管理员UID"]
  },
  "internal": {
    "api_secret": ""
  }
}
```

关键配置：

- `anchor.room_id`：直播间房间号，弹幕 Worker 用它连接直播弹幕。
- `anchor.ruid`：主播 UID，舰长列表接口需要它。
- `admin.uids`：管理员 B 站 UID 列表，启动时会自动注册为管理员角色。
- `flask.secret_key`：Flask session 和安全 token 使用的密钥，生产环境必须替换。
- `INTERNAL_API_SECRET`：内部 API 认证密钥；Docker Compose 从 `.env` 读取，必须固定保存，三个角色必须使用同一个值。不要每次启动临时生成。
- `internal.api_secret`：仅用于非 Docker 或兼容场景；Docker 部署以 `.env` 的 `INTERNAL_API_SECRET` 为准。
- `database.url`：默认 SQLite。相对路径会解析到项目目录下，例如 `sqlite:///data/app.db`。

## B 站授权

推荐在管理后台使用 Web 扫码授权。成功后系统会保存：

- DB 中的完整 Web `cookie_header`
- DB 中与 `cookie_header` 同源的 Web refresh token
- Cookie 元数据：最近验证时间、Cookie version、同步状态
- `settings.json` 中的 `bilibili_auth_mirror` 审计镜像；它只写出，不参与运行时读取

scheduler 会定时检查 B 站是否要求刷新 Cookie。无需刷新时保持现有 Cookie 不变；需要刷新时 `web` 会使用 Web refresh token 轮换 Cookie，并通知 `danmaku-worker` 重新加载。refresh token 失效、B 站风控或上游接口异常时，系统会保留最后可用 Cookie，并提示管理员重新扫码。

所有 B 站凭据都是敏感信息，不要提交到仓库、截图或日志。运行时不再读取 `settings.json` 里的旧 `bilibili` Cookie 字段；需要授权或修复错配时请重新 Web 扫码。

如果需要验证 B 站 Web QR 登录和 Cookie refresh 协议本身，可使用独立探针：

```bash
python scripts/web_qr_refresh_probe.py --terminal-qr
```

探针只用于人工排查上游协议变化。它不会读取 `settings.json`，不会连接或修改应用数据库，默认把原始请求审计文件写到 `scripts/web-refresh-probe/<timestamp>/`；这些输出已被 `.gitignore` 忽略，不要提交。

## Docker 常用命令

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

只有页面或管理后台异常时，优先看 `web`。只有弹幕鉴权异常时，优先看 `danmaku-worker`。只有自动同步和定时统计异常时，优先看 `scheduler`。

升级或大改前建议备份 SQLite 数据：

```bash
docker compose stop web danmaku-worker scheduler
mkdir -p backups
cp -a data backups/data-$(date +%Y%m%d-%H%M%S)
docker compose up -d
```

更完整的容器说明见 [DOCKER_README.md](DOCKER_README.md)。

## 目录结构

```text
bilibili-sailing-helper/
├── app.py                    # Flask 应用工厂、SocketIO 和启动辅助
├── config.py                 # settings.json / 环境变量配置加载
├── routes.py                 # 路由注册入口
├── route_handlers/           # 页面、后台和内部 API 路由
│   ├── public.py             # 首页、地址提交、开源说明
│   ├── auth.py               # 弹幕鉴权、登录、注册、重置密码
│   ├── internal.py           # Worker/Scheduler 内部 API
│   └── admin/                # 地址、舰长、舰礼、用户、Cookie 管理
├── runtime/
│   ├── web.py                # Web 角色入口
│   ├── danmaku_worker.py     # B 站直播弹幕 Worker
│   └── scheduler.py          # 定时任务角色
├── scripts/
│   ├── migrate_legacy_db.py     # 上游旧版 SQLite 到当前运行时 schema 的显式迁移脚本
│   └── web_qr_refresh_probe.py  # B 站 Web QR / Cookie refresh 协议探针
├── services/
│   ├── bilibili_live/        # 原生直播弹幕协议、客户端、事件归一化
│   ├── runtime_cookie_service.py
│   ├── internal_api_service.py
│   ├── auth_service.py
│   ├── guard_service.py
│   ├── guard_gift_service.py
│   ├── user_service.py
│   └── address_service.py
├── db/
│   └── models.py             # SQLite/SQLAlchemy 数据模型
├── templates/                # 页面模板
├── static/                   # 样式、字体、地区数据
├── tests/                    # 单元测试和运行时契约测试
├── data/                     # SQLite 数据库目录
├── logs/                     # 运行日志目录
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 主要页面和接口

用户侧：

- `GET /`：首页或当前登录用户地址表单。
- `GET /auth?uid=<uid>`：弹幕验证码鉴权页。
- `GET /login?uid=<uid>`：密码登录。
- `GET /register?uid=<uid>`：完成鉴权后的密码设置。
- `POST /submit`：提交收货地址。

管理员侧：

- `GET /admin/panel`：地址管理。
- `GET /admin/guards`：舰长名单管理。
- `GET /admin/companion-ranking`：陪伴榜/舰长视图。
- `GET /admin/guard-gifts`：舰礼资格和领取状态。
- `GET /admin/users`：用户与管理员权限。
- `GET /admin/cookie/status`：Cookie、授权和运行时角色状态。

内部 API：

- `POST /internal/runtime/heartbeat`
- `GET /internal/runtime/cookie`
- `POST /internal/danmaku/auth-event`
- `POST /internal/scheduler/job`
- `POST /internal/scheduler/result`

内部 API 只能由运行时角色调用，必须携带与 `INTERNAL_API_SECRET` 匹配的认证信息。

## 验证

```bash
python -m pytest
python -m compileall app.py config.py routes.py route_handlers runtime services db utils
```

涉及 Docker 配置时再运行：

```bash
docker compose config
docker compose build
```

## 技术栈

- 后端：Flask、Flask-Login、Flask-SocketIO、SQLAlchemy
- 数据库：SQLite，启用 `busy_timeout`，可用时启用 WAL
- 弹幕连接：`aiohttp` WebSocket + B 站直播弹幕协议解析
- 授权维护：B 站 Web 扫码授权、Cookie version 重载
- 容器化：Docker、Docker Compose
- 测试：pytest、pytest-flask

## License

AGPLv3
