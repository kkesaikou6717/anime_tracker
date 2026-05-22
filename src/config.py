"""
配置加载模块
- 加载 config.yaml
- 读取环境变量覆盖敏感信息
- 提供统一配置访问接口
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 配置缓存
_config: Dict[str, Any] = {}


def load_config(config_path: str = "config/config.yaml") -> Dict[str, Any]:
    """加载配置文件 + 环境变量覆盖"""
    global _config

    path = Path(config_path)
    if not path.exists():
        # 尝试从 /app 路径加载（Docker 环境）
        path = Path("/app") / config_path

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)

    # 环境变量注入敏感信息
    _apply_env_overrides()

    logger.info("配置加载完成")
    return _config


def _apply_env_overrides():
    """将环境变量覆盖到配置中"""
    at = _config.get("anime_tracker", {})

    # qBittorrent 密码
    qb_password = os.getenv("QB_PASSWORD")
    if qb_password and "qbittorrent" in at and at["qbittorrent"]:
        at["qbittorrent"]["password"] = qb_password

    # TMM API Key
    tmm_key = os.getenv("TMM_API_KEY")
    if tmm_key and "tmm" in at and at["tmm"]:
        at["tmm"]["api_key"] = tmm_key

    # Server酱 SendKey
    sc_sendkey = os.getenv("SERVERCHAN_SENDKEY")
    if sc_sendkey and "notification" in at and at["notification"]:
        ns = at["notification"]
        if "server_chan" not in ns or ns["server_chan"] is None:
            ns["server_chan"] = {}
        ns["server_chan"]["sendkey"] = sc_sendkey


def get_config() -> Dict[str, Any]:
    """获取当前配置（确保已加载）"""
    if not _config:
        load_config()
    return _config


def get_tracker_config() -> Dict[str, Any]:
    """获取 anime_tracker 子配置"""
    return get_config().get("anime_tracker", {})


# 便捷属性访问
@property
def resolution() -> str:
    return get_tracker_config().get("resolution", "1080p")


def get_sub_groups() -> list:
    return get_tracker_config().get("sub_group_priority", [])


def get_qb_config() -> Dict[str, Any]:
    return get_tracker_config().get("qbittorrent", {})


def get_tmm_config() -> Dict[str, Any]:
    return get_tracker_config().get("tmm", {})


def get_directories() -> Dict[str, str]:
    raw = get_tracker_config().get("directories", {})
    # 环境变量覆盖（Docker 部署时方便修改）
    env_temp = os.getenv("DOWNLOAD_TEMP_PATH")
    env_anime = os.getenv("ANIME_ARCHIVE_PATH")
    if env_temp:
        raw["temp"] = env_temp
    if env_anime:
        raw["anime"] = env_anime
    return raw


def get_temp_dir() -> str:
    """获取临时下载目录"""
    return get_directories().get("temp", "/volume1/Temp")


def get_anime_dir() -> str:
    """获取最终存储目录"""
    return get_directories().get("anime", "/volume1/Video/已归档/Anime")


def get_seeding_config() -> Dict[str, Any]:
    raw = get_tracker_config().get("seeding", {})
    # 环境变量覆盖
    env_hours = os.getenv("SEEDING_MIN_HOURS")
    if env_hours:
        raw["min_seeding_time_hours"] = int(env_hours)
    env_ratio = os.getenv("SEEDING_MIN_RATIO")
    if env_ratio:
        raw["min_ratio"] = float(env_ratio)
    return raw


def get_schedule_config() -> Dict[str, Any]:
    return get_tracker_config().get("schedule", {})


def get_bangumi_config() -> Dict[str, Any]:
    return get_tracker_config().get("bangumi", {})


def get_notification_config() -> Dict[str, Any]:
    return get_tracker_config().get("notification", {})


def get_sendkey() -> str:
    cfg = get_notification_config()
    return cfg.get("server_chan", {}).get("sendkey", "")
