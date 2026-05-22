"""
Bangumi API 封装模块
- 拉取季度新番列表
- 获取番剧详情
- 获取系列信息（多季匹配）
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

import httpx

import config

logger = logging.getLogger(__name__)


class BangumiAPI:
    """Bangumi API 客户端"""

    BASE_URL = "https://api.bangumi.tv"

    def __init__(self):
        cfg = config.get_bangumi_config()
        self.base_url = cfg.get("api_base", self.BASE_URL)
        self.user_agent = cfg.get("user_agent", "AnimeTracker/1.0")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"User-Agent": self.user_agent},
            timeout=30.0,
        )

    def close(self):
        self.client.close()

    def _get(self, path: str, params: dict = None) -> dict:
        """GET 请求"""
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_data: dict = None) -> dict:
        """POST 请求"""
        resp = self.client.post(path, json=json_data)
        resp.raise_for_status()
        return resp.json()

    # ================================================================
    # 季度番剧
    # ================================================================

    def get_current_season(self) -> str:
        """获取当前季度标识，如 '2026-07'"""
        now = datetime.now()
        year = now.year
        month = now.month

        if month <= 3:
            return f"{year}-01"
        elif month <= 6:
            return f"{year}-04"
        elif month <= 9:
            return f"{year}-07"
        else:
            return f"{year}-10"

    def get_season_anime(self, season: str = None) -> List[Dict[str, Any]]:
        """
        获取季度新番列表
        Args:
            season: 季度标识，如 '2026-07'，不传则取当季
        Returns:
            [{"id": 123, "name_cn": "...", "name": "...", "images": ...}, ...]
        """
        if season is None:
            season = self.get_current_season()

        logger.info(f"获取 {season} 季度新番列表...")
        try:
            params = {
                "type": 2,  # 动画
                "subject_type": 2,  # TV
                "limit": 100,
            }
            # Bangumi 日历 API
            data = self._get(f"/calendar", params=params)

            # 从日历中提取番剧（可能有重复，需要去重）
            seen = set()
            result = []
            today_weekday = datetime.now().weekday()  # 0=Monday

            for day_data in data:
                for item in day_data.get("items", []):
                    sid = item.get("id")
                    if sid and sid not in seen:
                        seen.add(sid)
                        result.append({
                            "bangumi_id": sid,
                            "series_id": item.get("series_id"),
                            "title_cn": item.get("name_cn", ""),
                            "title_jp": item.get("name", ""),
                            "summary": item.get("summary", ""),
                            "image": item.get("images", {}).get("large", ""),
                            "air_weekday": item.get("air_weekday"),
                            "total_episodes": item.get("total_episodes", 0),
                            "eps": item.get("eps", 0),
                            "rating": item.get("rating", {}).get("score", 0),
                            "season": season,
                        })

            logger.info(f"获取到 {len(result)} 部 {season} 新番")
            return result
        except Exception as e:
            logger.error(f"获取季度新番失败: {e}")
            return []

    # ================================================================
    # 番剧详情
    # ================================================================

    def get_subject_detail(self, subject_id: int) -> Optional[Dict[str, Any]]:
        """
        获取番剧详情
        Args:
            subject_id: Bangumi 条目 ID
        """
        try:
            data = self._get(f"/v0/subjects/{subject_id}")
            return {
                "bangumi_id": data.get("id"),
                "series_id": data.get("series_id"),
                "title_cn": data.get("name_cn", ""),
                "title_jp": data.get("name", ""),
                "summary": data.get("summary", ""),
                "total_episodes": data.get("total_episodes", 0),
                "eps": data.get("eps", 0),
                "air_date": data.get("date", ""),
                "image": data.get("images", {}).get("large", ""),
                "rating": data.get("rating", {}).get("score", 0),
                "platform": data.get("platform", ""),
            }
        except Exception as e:
            logger.error(f"获取番剧详情失败 (id={subject_id}): {e}")
            return None

    # ================================================================
    # 搜索
    # ================================================================

    def search_subjects(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜索番剧
        Args:
            keyword: 搜索关键词
            limit: 返回数量上限
        """
        try:
            params = {
                "type": 2,  # 动画
                "filter": {"type": [2]},  # TV
            }
            data = self._post(
                f"/v0/search/subjects",
                json_data={
                    "keyword": keyword,
                    "sort": "match",
                    "filter": {"type": [2]},
                    "limit": limit,
                }
            )
            results = []
            for item in data.get("data", []):
                results.append({
                    "bangumi_id": item.get("id"),
                    "series_id": item.get("series_id"),
                    "title_cn": item.get("name_cn", ""),
                    "title_jp": item.get("name", ""),
                    "image": item.get("images", {}).get("large", ""),
                    "summary": item.get("summary", ""),
                    "air_date": item.get("date", ""),
                })
            return results
        except Exception as e:
            logger.error(f"搜索番剧失败 (keyword={keyword}): {e}")
            return []

    # ================================================================
    # 系列信息（多季匹配）
    # ================================================================

    def get_series_detail(self, series_id: int) -> Optional[Dict[str, Any]]:
        """获取系列详情（含所有季）"""
        try:
            return self._get(f"/v0/series/{series_id}/subjects")
        except Exception as e:
            logger.error(f"获取系列详情失败 (series_id={series_id}): {e}")
            return None

    def find_previous_season(self, series_id: int, current_season_number: int) -> Optional[Dict]:
        """
        查找系列的前一季
        Returns: 找到的 subject 信息或 None
        """
        try:
            data = self._get(f"/v0/series/{series_id}/subjects")
            for subject in data:
                # 检查是否是前季
                if subject.get("subject_type") == 2:
                    return {
                        "bangumi_id": subject.get("id"),
                        "title_cn": subject.get("name_cn", ""),
                        "title_jp": subject.get("name", ""),
                        "date": subject.get("date", ""),
                    }
            return None
        except Exception as e:
            logger.error(f"查找前季失败: {e}")
            return None


# 全局单例
_bangumi: Optional[BangumiAPI] = None


def get_bangumi() -> BangumiAPI:
    global _bangumi
    if _bangumi is None:
        _bangumi = BangumiAPI()
    return _bangumi
