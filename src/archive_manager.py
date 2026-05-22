"""
归档管理模块（新架构）
- 目录结构简化：所有动画统一放在 /volume1/Video/已归档/Anime/
- 已取消 未完结/已完结 子目录区分
- 归档 = 仅更新数据库状态（finished → archived），文件不动

目录结构：
  /已归档/Anime/番剧名/  ← 唯一存储位置
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import config, db
from notifier import get_notifier

logger = logging.getLogger(__name__)


def check_and_archive() -> Dict:
    """
    检查是否需要归档

    新架构下不移动文件，仅更新数据库状态：
    finished → archived

    Returns:
        {"action": "archived"|"none", "details": {...}}
    """
    result = {"action": "none", "details": {}}

    # 获取状态为 finished 的追番
    finished_animes = db.get_tracking_list(status="finished")

    if not finished_animes:
        logger.debug("无待归档番剧")
        return result

    archived = 0
    for anime in finished_animes:
        try:
            db.update_tracking_status(anime["id"], "archived")
            archived += 1
            logger.info(f"[归档完成] {anime['title_cn']}")
        except Exception as e:
            logger.error(f"归档失败 {anime['title_cn']}: {e}")
            continue

    if archived > 0:
        continuing = len(db.get_tracking_list(status="ongoing"))
        result["action"] = "archived"
        result["details"] = {
            "archived": archived,
            "continuing": continuing,
        }

        notifier = get_notifier()
        notifier.notify_archive_complete(
            season="当前季度",
            finished_count=archived,
            continuing_count=continuing,
        )

    return result


def trigger_manual_archive() -> Dict:
    """手动触发归档（供 API 调用）"""
    return check_and_archive()
