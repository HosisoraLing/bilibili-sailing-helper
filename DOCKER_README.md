# Docker 部署说明

## 快速开始

### 1. 准备配置文件

复制示例配置文件并填写：
```bash
cp settings.json.example settings.json
# 编辑 settings.json 填写你的配置
```

### 2. 构建并启动

```bash
# 构建镜像（首次需要较长时间）
docker compose build

# 启动服务
docker compose up -d

# 查看日志
docker compose logs -f
```

### 3. 常用命令

```bash
# 停止服务
docker compose down

# 重启服务
docker compose restart

# 查看日志
docker compose logs -f

# 进入容器
docker compose exec app bash
```

## 数据持久化

- **数据库**: Docker volume `sailing-data` -> `/app/data`
- **日志**: Docker volume `sailing-logs` -> `/app/logs`
- **配置**: bind mount `./settings.json` -> `/app/settings.json`

## 查看错误日志

```bash
# 查看容器内的错误日志
docker compose exec app cat /app/logs/error.log

# 或者从宿主机查看（如果使用默认volume）
docker run --rm -v sailing-logs:/logs alpine cat /logs/error.log
```

## SSL 配置（可选）

1. 将证书文件放到 `ssl/` 目录
2. 在 `settings.json` 中配置：
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
3. 取消 `docker-compose.yml` 中 SSL 挂载的注释
4. 重启服务：`docker compose restart`

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| PYTHONUNBUFFERED | Python输出不缓冲 | 1 |
| PYTHONDONTWRITEBYTECODE | 不生成pyc文件 | 1 |
| TZ | 时区 | Asia/Shanghai |

## 资源限制

默认配置：
- 内存限制: 512MB
- 内存预留: 128MB

可在 `docker-compose.yml` 中调整 `deploy.resources` 配置。
