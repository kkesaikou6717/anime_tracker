"""
初始扫描模块 — 首次部署时扫描已有动漫目录
- 扫描 /volume1/Video/已归档/Anime/ 下已有动漫
- 自动导入数据库
- 支持全量/增量模式
- 防重复导入
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

import config
import db

logger = logging.getLogger(__name__)


class InitScanner:
    """已有动漫目录扫描器"""

    # 常见的集数匹配模式
    EP_PATTERNS = [
        re.compile(r'[Ee][Pp]?\s*(\d{1,4})'),          # EP01, E01, ep01
        re.compile(r'[Ee]pisode\s*(\d{1,4})'),          # Episode 01
        re.compile(r'第\s*(\d{1,4})\s*[话話集]'),        # 第01话 / 第01集
        re.compile(r'[\[【〔](\d{1,4})[\]】〕]'),        # [01]
        re.compile(r'[ ._-](\d{1,4})[ ._-]'),            # _01_
        re.compile(r'[ ._-](\d{1,4})\.(?:mkv|mp4|avi)'), # 01.mkv
    ]

    def __init__(self):
        self.dirs = config.get_directories()
        self.anime_path = Path(self.dirs.get("anime", "/volume1/Video/已归档/Anime"))

    def scan(self, full: bool = False) -> Dict:
        """
        扫描已有动漫目录

        Args:
            full: True=全量扫描, False=增量(只扫未入库的)

        Returns:
            {"found": 5, "imported": 3, "skipped": 2, "errors": [...]}
        """
        result = {
            "found": 0,
            "imported": 0,
            "skipped": 0,
            "errors": [],
        }

        if not self.anime_path.exists():
            logger.warning(f"目录不存在，跳过: {self.anime_path}")
            return result

        logger.info(f"扫描目录: {self.anime_path}")

        for anime_dir in self.anime_path.iterdir():
            if not anime_dir.is_dir():
                continue

            try:
                r = self._process_anime_dir(anime_dir, full)
                result["found"] += 1
                if r == "imported":
                    result["imported"] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                logger.error(f"处理目录失败 {anime_dir}: {e}")
                result["errors"].append(str(anime_dir))

        logger.info(f"扫描完成: found={result['found']}, "
                     f"imported={result['imported']}, "
                     f"skipped={result['skipped']}")
        return result

    def _process_anime_dir(self, anime_dir: Path, full: bool) -> str:
        """
        处理单个动漫目录
        Returns: 'imported' | 'skipped'
        """
        dir_name = anime_dir.name
        logger.info(f"  → {dir_name}")

        # 从目录名尝试提取番剧名和季度信息
        title_cn = dir_name
        season_number = 1

        season_match = re.match(r'^(.+?)\s*[Ss]eason\s*(\d{1,2})$', dir_name)
        if season_match:
            title_cn = season_match.group(1).strip()
            season_number = int(season_match.group(2))

        # 检查是否已在数据库中
        existing = self._find_existing_anime(title_cn, season_number)
        if existing and not full:
            logger.debug(f"    已存在: {title_cn} (id={existing['id']})")
            return "skipped"

        # 扫描目录中的视频文件
        episodes = self._find_episodes(anime_dir)
        logger.info(f"    发现 {len(episodes)} 集")

        # 导入数据库
        anime_id = None
        if not existing:
            # 创建追番记录（默认 finished，后续可改为 ongoing）
            anime_id = db.upsert_tracking({
                "title_cn": title_cn,
                "title_jp": "",
                "season": self._guess_season(anime_dir),
                "season_number": season_number,
                "resolution": "1080p",
                "total_episodes": len(episodes),
                "status": "finished",  # 已归档的内容标记为 finished
            })
            logger.info(f"    新建追番记录: id={anime_id}, status=finished")
        else:
            anime_id = existing["id"]

        # 导入下载历史（已归档的标记为已刮削）
        imported_count = 0
        for ep in episodes:
            if not db.is_episode_downloaded(anime_id, ep):
                db.insert_download({
                    "anime_id": anime_id,
                    "episode": ep,
                    "file_path": str(anime_dir),
                    "status": "completed",
                    "scraped": 1,  # 已归档的默认已刮削
                })
                imported_count += 1

        conn = db.get_connection()
        conn.execute("""
            UPDATE download_history
            SET scraped = 1, scraped_at = datetime('now', 'localtime')
            WHERE anime_id = ? AND scraped = 0
        """, (anime_id,))
        conn.commit()
        conn.close()

        logger.info(f"    导入 {imported_count} 集下载记录（已标记已刮削）")
        return "imported"

    def _find_episodes(self, anime_dir: Path) -> List[int]:
        """递归查找目录中的视频文件，提取集数"""
        episodes = set()

        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.ts', '.m2ts'}

        for root, dirs, files in os.walk(anime_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in video_exts:
                    continue

                ep = self._extract_episode(fname)
                if ep and ep > 0 and ep < 2000:  # 合理范围
                    episodes.add(ep)

        return sorted(episodes)

    def _extract_episode(self, filename: str) -> Optional[int]:
        """从文件名提取集数"""
        for pattern in self.EP_PATTERNS:
            match = pattern.search(filename)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    def _find_existing_anime(self, title_cn: str, season_number: int) -> Optional[Dict]:
        """在数据库中查找已存在的番剧记录"""
        tracking = db.get_tracking_list()
        for t in tracking:
            if t.get("title_cn") == title_cn and t.get("season_number") == season_number:
                return t
        return None

    def _guess_season(self, anime_dir: Path) -> str:
        """根据目录的修改时间猜测所属季度"""
        try:
            mtime = os.path.getmtime(anime_dir)
            from datetime import datetime
            dt = datetime.fromtimestamp(mtime)
            year = dt.year
            month = dt.month

            if month <= 3:
                return f"{year}-01"
            elif month <= 6:
                return f"{year}-04"
            elif month <= 9:
                return f"{year}-07"
            else:
                return f"{year}-10"
        except Exception:
            return "unknown"


def run_scan(full: bool = False) -> Dict:
    """运行初始扫描（供 API 调用）"""
    scanner = InitScanner()
    return scanner.scan(full=full)
