"""
多季番剧处理模块（新架构）
- 通过 Bangumi series_id 匹配多季
- 自动创建 Season XX 子目录结构

目录结构：
  /已归档/Anime/番剧名/Season 01/  ← 第一季
  /已归档/Anime/番剧名/Season 02/  ← 第二季（续播）
"""

import logging
import re
from pathlib import Path
from typing import Optional, Dict, List

import config, db
from bangumi import get_bangumi

logger = logging.getLogger(__name__)


class MultiSeasonHandler:
    """多季番剧处理器"""

    def __init__(self):
        self.dirs = config.get_directories()
        self.anime_dir = Path(self.dirs.get("anime", "/volume1/Video/已归档/Anime"))

    def check_multi_season(self, bangumi_id: int, series_id: int,
                           title_cn: str) -> Optional[Dict]:
        """
        检查番剧是否属于多季系列

        Args:
            bangumi_id: Bangumi 条目 ID
            series_id: Bangumi 系列 ID
            title_cn: 中文标题

        Returns:
            None = 新番独立处理
            {"is_sequel": True, "season_number": N, ...}
        """
        if not series_id:
            return None

        # 在本地数据库中查找同 series_id 的记录
        tracking = db.get_tracking_list()
        previous = None
        for t in tracking:
            if t.get("series_id") == series_id and t["id"] != bangumi_id:
                if not previous or t.get("season_number", 1) > previous.get("season_number", 1):
                    previous = t

        if previous:
            return {
                "is_sequel": True,
                "series_id": series_id,
                "previous_season": previous.get("season_number", 1),
                "previous_title": previous.get("title_cn", ""),
                "previous_db_id": previous["id"],
                "season_number": previous.get("season_number", 1) + 1,
            }

        return None

    def setup_multi_season_dir(self, title_cn: str, season_number: int) -> Path:
        """
        创建多季番剧目录结构
        /已归档/Anime/番剧名/Season XX/
        """
        series_dir = self.anime_dir / title_cn
        season_dir = series_dir / f"Season {season_number:02d}"
        season_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"多季目录: {season_dir}")
        return season_dir

    def find_previous_season_path(self, title_cn: str,
                                  season_number: int) -> Optional[Path]:
        """
        查找前季路径
        /已归档/Anime/番剧名/Season XX/
        """
        prev_season = season_number - 1
        if prev_season < 1:
            return None

        path = self.anime_dir / title_cn / f"Season {prev_season:02d}"
        if path.exists():
            return path

        return None


# 全局单例
_handler: Optional[MultiSeasonHandler] = None


def get_multi_season_handler() -> MultiSeasonHandler:
    global _handler
    if _handler is None:
        _handler = MultiSeasonHandler()
    return _handler


def check_and_setup_multi_season(bangumi_id: int, series_id: int,
                                 title_cn: str) -> Optional[Dict]:
    """
    检查并设置多季番剧（供 API 调用）
    """
    handler = get_multi_season_handler()
    result = handler.check_multi_season(bangumi_id, series_id, title_cn)

    if result and result.get("is_sequel"):
        season_num = result.get("season_number", 1)
        handler.setup_multi_season_dir(title_cn, season_num)
        logger.info(f"多季匹配成功: {title_cn} Season {season_num}")

    return result
