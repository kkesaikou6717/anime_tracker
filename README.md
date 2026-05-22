# Anime Tracker — Python 后端服务

> 自动化追番系统 | v1.0.0 | Raana (Dev)

## 项目结构

```
anime-tracker/
├── docker-compose.yml          # Docker Compose 编排
├── Dockerfile                  # 镜像构建
├── .env.example                # 环境变量模板
├── requirements.txt            # Python 依赖
├── config/
│   ├── config.yaml             # 主配置
│   └── logging.yaml            # 日志配置
└── src/
    ├── main.py                 # 入口
    ├── api_server.py           # REST API (FastAPI, 10+接口)
    ├── scheduler.py            # 定时调度 (APScheduler)
    ├── bangumi.py              # Bangumi API
    ├── dmhy_search.py          # 动漫花园搜索
    ├── qb_manager.py           # qBittorrent 管理
    ├── tmm_trigger.py          # TMM HTTP API 触发
    ├── seed_manager.py         # 做种管理
    ├── archive_manager.py      # 归档管理
    ├── multi_season.py         # 多季处理
    ├── db.py                   # SQLite 数据库
    ├── init_scanner.py         # 初始扫描
    ├── notifier.py             # Server酱 通知
    └── config.py               # 配置加载
```

## 快速部署

```bash
# 1. 复制到 NAS
scp -r anime-tracker/ user@nas:/volume1/docker/anime-tracker/

# 2. 配置环境变量
cd /volume1/docker/anime-tracker/
cp .env.example .env
nano .env  # 填入 QB_PASSWORD / TMM_API_KEY / SERVERCHAN_SENDKEY

# 3. 启动
docker compose up -d

# 4. 验证
curl http://localhost:8765/api/health
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/season/current` | 当季新番 |
| POST | `/api/tracking/save` | 保存追番 |
| GET | `/api/tracking/list` | 追番列表 |
| POST | `/api/search` | 搜索种子 |
| POST | `/api/download` | 下载种子 |
| GET | `/api/status/daily` | 今日摘要 |
| GET | `/api/status/seed` | 做种状态 |
| POST | `/api/archive/trigger` | 触发归档 |
| POST | `/api/notify/test` | 通知测试 |

## 环境变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `QB_PASSWORD` | qBittorrent 密码 | ✅ |
| `TMM_API_KEY` | TMM HTTP API Key | ✅ |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey | ✅ |

## 定时任务

| 任务 | 频率 |
|------|------|
| 🔍 搜索新集 | 每小时 |
| 📊 日报 | 每晚 20:00 |
| 🌱 做种检查 | 每12小时 |
| 📦 归档检查 | 每周日 03:00 |
| 📥 下载监控 | 每10分钟 |
