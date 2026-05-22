"""
DMHY 搜索模块 — 动漫花园 (share.dmhy.org) 搜索与种子页解析
- 搜索番剧种子
- 按字幕组 + 分辨率匹配
- 解析种子详情页获取磁力/种子链接
"""

import re
import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin, quote

import httpx
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

# 动漫花园基础 URL
DMHY_BASE = "https://share.dmhy.org"


class DMHYSearch:
    """动漫花园搜索客户端"""

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self):
        self.client.close()

    def search(self, keyword: str, sub_group: str = None,
               resolution: str = None, max_pages: int = 3) -> List[Dict]:
        """
        搜索动漫花园种子

        Args:
            keyword: 搜索关键词（番剧名）
            sub_group: 字幕组过滤（可选）
            resolution: 分辨率过滤（默认 1080p）
            max_pages: 最大搜索页数

        Returns:
            [{"title": "...", "magnet": "...", "torrent_url": "...",
              "size": "...", "date": "...", "sub_group": "..."}, ...]
        """
        if resolution is None:
            resolution = config.get_tracker_config().get("resolution", "1080p")

        all_results = []

        for page in range(1, max_pages + 1):
            url = f"{DMHY_BASE}/topics/list/page/{page}"
            params = {"keyword": keyword}

            try:
                resp = self.client.get(url, params=params)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"DMHY 搜索失败 (page={page}, keyword={keyword}): {e}")
                break

            soup = BeautifulSoup(resp.text, "lxml")
            tbody = soup.find("tbody", id="topic_list")

            if not tbody:
                logger.debug(f"DMHY 搜索结果为空 (page={page})")
                break

            rows = tbody.find_all("tr")
            for row in rows:
                try:
                    result = self._parse_row(row)
                    if result:
                        all_results.append(result)
                except Exception as e:
                    logger.debug(f"解析行失败: {e}")
                    continue

            # 检查是否有下一页
            pagination = soup.find("div", class_="pagination")
            if not pagination or not pagination.find("a", string="下一頁"):
                break

        logger.info(f"DMHY 搜索完成: keyword={keyword}, 共 {len(all_results)} 条结果")

        # 按字幕组优先级排序
        if sub_group:
            all_results = self._sort_by_sub_group(all_results, sub_group)

        return all_results

    def _parse_row(self, row) -> Optional[Dict]:
        """解析搜索结果行"""
        # 获取标题
        title_tag = row.find("a", class_="sort-2")
        if not title_tag:
            return None
        title = title_tag.get("title", "").strip() or title_tag.text.strip()

        # 详情页链接
        detail_url = title_tag.get("href", "")
        if detail_url:
            detail_url = urljoin(DMHY_BASE, detail_url)

        # 字幕组标签
        sub_group = ""
        tag_span = row.find("span", class_="tag")
        if tag_span:
            sub_group = tag_span.text.strip()

        # 磁力链接
        magnet = ""
        magnet_tag = row.find("a", class_="magnet")
        if magnet_tag:
            magnet = magnet_tag.get("href", "")

        # 种子链接
        torrent_url = ""
        torrent_tag = row.find("a", class_="download")
        if torrent_tag:
            torrent_url = torrent_tag.get("href", "")

        # 大小
        size = ""
        size_td = row.select_one("td:nth-child(6)")
        if size_td:
            size = size_td.text.strip()

        # 日期
        date = ""
        date_span = row.find("span", string=re.compile(r"\d{4}-\d{2}-\d{2}"))
        if date_span:
            date = date_span.text.strip()
        else:
            date_td = row.select_one("td:nth-child(2)")
            if date_td:
                date = date_td.text.strip()

        return {
            "title": title,
            "detail_url": detail_url,
            "magnet": magnet,
            "torrent_url": torrent_url,
            "size": size,
            "date": date,
            "sub_group": sub_group,
        }

    def _sort_by_sub_group(self, results: List[Dict], preferred_group: str) -> List[Dict]:
        """按字幕组优先级排序：优先匹配的在前"""
        matched = [r for r in results if preferred_group in r.get("sub_group", "")]
        others = [r for r in results if preferred_group not in r.get("sub_group", "")]
        return matched + others

    def get_torrent_detail(self, detail_url: str) -> Optional[Dict]:
        """
        获取种子详情页信息
        Returns: {"magnet": "...", "torrent_url": "...", "info_hash": "...", ...}
        """
        try:
            resp = self.client.get(detail_url)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"获取种子详情失败: {e}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        result = {"detail_url": detail_url}

        # 磁力链接
        magnet_tag = soup.find("a", id="a_magnet")
        if magnet_tag:
            result["magnet"] = magnet_tag.get("href", "")

        # 种子下载链接
        torrent_tag = soup.find("a", id="download")
        if torrent_tag:
            result["torrent_url"] = torrent_tag.get("href", "")

        # info hash
        if "magnet" in result:
            match = re.search(r"btih:([a-fA-F0-9]{40})", result.get("magnet", ""))
            if match:
                result["info_hash"] = match.group(1).upper()

        return result

    def search_anime_episode(self, title_cn: str, episode: int,
                             preferred_sub_group: str = None,
                             resolution: str = "1080p") -> Optional[Dict]:
        """
        搜索特定番剧的特定集数

        Args:
            title_cn: 番剧中文名
            episode: 集数
            preferred_sub_group: 首选字幕组
            resolution: 分辨率

        Returns:
            最佳匹配的种子信息，或 None
        """
        # 构建搜索关键词
        ep_str = f"{episode:02d}"
        keyword = f"{title_cn} {ep_str}"

        logger.info(f"搜索番剧: {keyword}")

        results = self.search(keyword, sub_group=preferred_sub_group, resolution=resolution)

        if not results:
            logger.info(f"未找到: {keyword}")
            return None

        # 按字幕组优先级匹配
        priorities = config.get_sub_groups()

        best = None
        for group in priorities:
            for r in results:
                title = r.get("title", "")
                # 检查是否匹配字幕组 + 分辨率 + 集数
                if group in title or group in r.get("sub_group", ""):
                    if resolution in title:
                        if ep_str in title or f"第{ep_str}话" in title:
                            best = r
                            best["matched_group"] = group
                            logger.info(f"匹配到: [{group}] {title}")
                            break
            if best:
                break

        # 如果首选没匹配到，用第一个结果
        if not best and results:
            best = results[0]
            best["matched_group"] = best.get("sub_group", "未知")
            logger.info(f"降级匹配: [{best['matched_group']}] {best['title']}")

        return best


# 全局单例
_dmhy: Optional[DMHYSearch] = None


def get_dmhy() -> DMHYSearch:
    global _dmhy
    if _dmhy is None:
        _dmhy = DMHYSearch()
    return _dmhy
