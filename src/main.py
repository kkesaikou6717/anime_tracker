"""
Anime Tracker — 入口模块
- 初始化数据库
- 加载配置
- 启动 FastAPI + APScheduler
"""

import os
import sys
import logging
import logging.config
from pathlib import Path

import yaml
import uvicorn

# 确保 src 目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, get_tracker_config
from db import init_db
from scheduler import setup_scheduler, stop_scheduler


def setup_logging():
    """配置日志"""
    log_config_path = os.getenv("LOG_CONFIG", "config/logging.yaml")

    # Docker 环境下路径调整
    if not Path(log_config_path).exists():
        log_config_path = "/app/config/logging.yaml"

    if Path(log_config_path).exists():
        with open(log_config_path, "r", encoding="utf-8") as f:
            log_config = yaml.safe_load(f)
        logging.config.dictConfig(log_config)
    else:
        # 降级：基础日志配置
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    logger = logging.getLogger(__name__)
    logger.info("日志系统初始化完成")


def main():
    """主入口"""
    # 1. 日志
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("🎸 Anime Tracker v1.0.0 启动中...")
    logger.info("=" * 60)

    # 2. 配置
    try:
        load_config()
        cfg = get_tracker_config()
        logger.info(f"配置加载成功: resolution={cfg.get('resolution')}, "
                     f"qb_url={cfg.get('qbittorrent', {}).get('url')}")
    except Exception as e:
        logger.fatal(f"配置加载失败: {e}")
        sys.exit(1)

    # 3. 数据库
    try:
        init_db()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.fatal(f"数据库初始化失败: {e}")
        sys.exit(1)

    # 4. 定时调度器
    try:
        setup_scheduler()
    except Exception as e:
        logger.error(f"调度器启动失败: {e}")

    # 5. 启动 API 服务
    logger.info("启动 FastAPI 服务 (0.0.0.0:8765)...")
    try:
        uvicorn.run(
            "api_server:app",
            host="0.0.0.0",
            port=8765,
            log_config=None,  # 使用自定义日志
            log_level="info",
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
    finally:
        stop_scheduler()
        logger.info("Anime Tracker 已停止")


if __name__ == "__main__":
    main()
