# CHANGELOG v3.0 — 新架构重构

## 变更概述

根据博哥新方案，简化目录结构，重构下载后处理流程。

### v3.0.1（博哥确认后修正）
- 环境变量名改为 `DOWNLOAD_TEMP_PATH` / `ANIME_ARCHIVE_PATH`
- 做种时间改为 **24 小时**
- 新增 `POST /api/retry/unscraped` 端点：重新处理已下载但未刮削的文件
- 迁移期的 上伊那牡丹 EP1~6 可用此端点一键补处理

### 目录结构变更

```
旧架构:
  /volume1/Video/Download/          ← qB 下载
  /volume1/Video/已归档/未完结/      ← 在播
  /volume1/Video/已归档/已完结/      ← 已归档

新架构:
  /volume1/Temp/                     ← 临时下载（可清理）
  /volume1/Video/已归档/Anime/       ← 最终存储（唯一目录）
```

### 流程变更

```
① 下载链接 → qBittorrent → 保存到 /volume1/Temp/
      ↕ 下载完成
② job_download_monitor 检测完成
      ↕
③ 复制文件到 /volume1/Video/已归档/Anime/{番剧名}/
      ↕
④ 触发 TMM 刮削 (update → scrape → rename)
      ↕ 做种达标（默认 24h / 比率 2.0）
⑤ 删除 qB 任务 + 清理 Temp 文件
```

### 修改的文件

| 文件 | 变更 |
|------|------|
| `config/config.yaml` | 目录改为 `temp` + `anime`，做种默认 24h |
| `.env.example` | 新增 `ANIME_TEMP_DIR` / `ANIME_ARCHIVE_DIR` / `SEEDING_MIN_*` |
| `src/config.py` | 新增 `get_temp_dir()` / `get_anime_dir()`，支持 env 覆盖 |
| `src/scheduler.py` | `job_download_monitor` 重写：复制→刮削流程；新增辅助函数 |
| `src/seed_manager.py` | 清理时 `delete_files=True` 删除 Temp，补刀清理 |
| `src/init_scanner.py` | 扫描路径改为 `Anime/`，取消未完结/已完结区分 |
| `src/archive_manager.py` | 改为仅更新 DB 状态，不再移动文件 |
| `src/multi_season.py` | 目录创建路径改为 `Anime/` |
| `src/notifier.py` | 通知文案适配新流程 |
| `docker-compose.yml` | 挂载改为 Temp + Anime |

### 部署说明

1. 备份现有 config.yaml（特别是 QB_PASSWORD / TMM_API_KEY）
2. 复制新代码到 NAS
3. 在 NAS 上创建新目录：
   ```bash
   mkdir -p /volume1/Temp
   mkdir -p /volume1/Video/已归档/Anime
   ```
4. 重启容器：
   ```bash
   docker compose down
   docker compose up -d
   ```
6. 运行初始扫描（可选）：
   ```bash
   curl -X POST http://localhost:8765/api/scan/trigger -H 'Content-Type: application/json' -d '{"full": true}'
   ```
