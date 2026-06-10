# B站舰礼地址收集助手

B站舰长/陪伴榜用户地址收集网页，使用Flask + SocketIO搭建。

关注小蝰Kuii谢谢喵~

## 功能特性

- 🔐 弹幕鉴权 - 通过发送弹幕验证码完成身份验证
- 📦 地址收集 - 舰长/陪伴榜用户自助填写收货地址
- 🎁 礼物管理 - 自动统计舰长礼物领取资格
- 👑 管理后台 - 地址导出CSV、舰长列表管理
- 📝 错误日志 - ERROR级别日志自动保存到本地文件
- 🐳 Docker部署 - 一键部署脚本

## 快速开始

### 方式一：Docker部署（推荐）

```bash
# 克隆项目
git clone https://github.com/HosisoraLing/bilibili-sailing-helper.git
cd bilibili-sailing-helper

# 复制配置文件并填写
cp settings.json.example settings.json
# 编辑 settings.json 填写你的配置

# 一键部署
./deploy.sh
```

### 方式二：手动部署

```bash
# 克隆项目
git clone https://github.com/HosisoraLing/bilibili-sailing-helper.git
cd bilibili-sailing-helper

# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填写
cp settings.json.example settings.json
# 编辑 settings.json 填写你的配置

# 启动服务
python app.py
```

## 配置说明

编辑 `settings.json`：

```json
{
    "anchor": {
        "nickname": "主播昵称",
        "room_id": 123456,
        "ruid": 789012
    },
    "bilibili": {
        "SESSDATA": "",
        "bili_jct": "",
        "buvid3": ""
    },
    "database": {
        "url": "sqlite:///data/app.db"
    },
    "flask": {
        "secret_key": "随机密钥",
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
    }
}
```

### 获取B站Cookie

推荐方式是在管理后台使用 B 站 APP 扫码授权。首次授权成功后，系统会保存 refresh token 和验证后的 Web Cookie；后续由定时任务在 `SESSDATA` 临期时自动刷新。

`SESSDATA`、`bili_jct`、`buvid3`、TV `access_token`、TV `refresh_token` 都是敏感凭据，不要提交到仓库、截图或日志。如果 refresh token 失效或 B 站风控拦截，管理后台会提示重新扫码授权。

手动填写 Cookie 仍可用于排障，但无法提供自动续期能力。

## 目录结构

```
bilibili-sailing-helper/
├── app.py              # 主程序入口
├── config.py           # 配置加载
├── routes.py           # 路由定义
├── constants.py        # 常量定义
├── decorators.py       # 装饰器
├── services/           # 业务逻辑
│   ├── auth_service.py       # 鉴权服务
│   ├── danmaku_listener.py   # 弹幕监听
│   ├── guard_service.py      # 舰长服务
│   ├── user_service.py       # 用户服务
│   ├── admin_service.py      # 管理服务
│   └── address_service.py    # 地址服务
├── templates/          # HTML模板
├── static/             # 静态资源
├── utils/              # 工具模块
│   └── log_utils.py    # 日志工具
├── data/               # 数据库文件
├── logs/               # 错误日志
├── Dockerfile          # Docker镜像配置
├── docker-compose.yml  # Docker编排配置
├── deploy.sh           # 一键部署脚本
└── requirements.txt    # Python依赖
```

## Docker部署

```bash
# 构建并启动
docker compose build
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 查看错误日志
docker compose exec app cat /app/logs/error.log
```

详见 [DOCKER_README.md](DOCKER_README.md)

## 错误日志

ERROR级别日志自动保存到 `logs/error.log`，支持日志轮转（最大10MB，保留5个备份）。

```bash
# 查看错误日志
tail -f logs/error.log

# Docker环境
docker compose exec app cat /app/logs/error.log
```

## 访问地址

- 首页：`http://localhost:7111/`
- 管理后台：`http://localhost:7111/admin/panel`
- 鉴权页面：`http://localhost:7111/auth?uid=xxx`

## 技术栈

- **后端**: Flask + Flask-SocketIO + SQLAlchemy
- **数据库**: SQLite
- **弹幕监听**: [blivedm](https://github.com/xfgryujk/blivedm)
- **二维码生成**: [python-qrcode](https://github.com/lincolnloop/python-qrcode)
- **容器化**: Docker + Docker Compose

## 第三方依赖

| 项目 | 用途 | 许可证 |
|------|------|--------|
| [Flask](https://github.com/pallets/flask) | Web框架 | BSD-3-Clause |
| [Flask-SocketIO](https://github.com/miguelgrinberg/flask-socketio) | WebSocket支持 | MIT |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | ORM | MIT |
| [blivedm](https://github.com/xfgryujk/blivedm) | B站弹幕监听 | MIT |
| [aiohttp](https://github.com/aio-libs/aiohttp) | 异步HTTP | Apache-2.0 |
| [requests](https://github.com/psf/requests) | HTTP库 | Apache-2.0 |
| [python-qrcode](https://github.com/lincolnloop/python-qrcode) | 二维码生成 | BSD |

详见 [开源项目使用说明](/opensource)

## License

AGPLv3
