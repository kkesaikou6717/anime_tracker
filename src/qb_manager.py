"""
qBittorrent WebUI API 管理模块
- 导入种子（URL / 磁力链接）
- 查询下载状态
- 查询做种状态
- 删除种子和文件
"""

import logging
from typing import Optional, List, Dict, Any

import httpx

import config

logger = logging.getLogger(__name__)


class QBitManager:
    """qBittorrent WebUI API 客户端"""

    def __init__(self):
        cfg = config.get_qb_config()
        self.base_url = cfg.get("url", "http://localhost:8085")
        self.username = cfg.get("username", "admin")
        self.password = cfg.get("password", "")

        if not self.password:
            logger.warning("qBittorrent 密码未配置！请设置 QB_PASSWORD 环境变量")

        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=30.0,
        )
        self._authenticated = False

    def close(self):
        self.client.close()

    def _ensure_auth(self):
        """确保已登录"""
        if self._authenticated:
            return

        try:
            resp = self.client.post(
                "/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
            )
            resp.raise_for_status()
            if resp.text == "Ok.":
                self._authenticated = True
                logger.debug("qBittorrent 登录成功")
            else:
                logger.error(f"qBittorrent 登录失败: {resp.text}")
                raise RuntimeError("qBittorrent 登录失败")
        except Exception as e:
            logger.error(f"qBittorrent 登录异常: {e}")
            raise

    # ================================================================
    # 种子操作
    # ================================================================

    def add_torrent(self, magnet_or_url: str, save_path: str = None,
                    category: str = "anime") -> bool:
        """
        导入种子/磁力链接到 qBittorrent

        Args:
            magnet_or_url: 磁力链接或种子URL
            save_path: 保存路径
            category: 分类标签

        Returns:
            是否成功
        """
        self._ensure_auth()

        form_data = {
            "urls": magnet_or_url,
            "category": category,
        }

        if save_path:
            form_data["savepath"] = save_path

        try:
            resp = self.client.post("/api/v2/torrents/add", data=form_data)
            if resp.text == "Ok.":
                logger.info(f"种子已添加: {magnet_or_url[:80]}...")
                return True
            else:
                logger.error(f"添加种子失败: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"添加种子异常: {e}")
            return False

    def add_torrent_file(self, torrent_data: bytes, save_path: str = None,
                         category: str = "anime") -> bool:
        """上传 .torrent 文件"""
        self._ensure_auth()

        files = {"torrents": ("download.torrent", torrent_data, "application/x-bittorrent")}
        data = {"category": category}
        if save_path:
            data["savepath"] = save_path

        try:
            resp = self.client.post("/api/v2/torrents/add", files=files, data=data)
            if resp.text == "Ok.":
                logger.info("种子文件已添加")
                return True
            else:
                logger.error(f"添加种子文件失败: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"添加种子文件异常: {e}")
            return False

    # ================================================================
    # 状态查询
    # ================================================================

    def get_all_torrents(self, filter_status: str = None) -> List[Dict]:
        """
        获取所有种子列表

        Args:
            filter_status: 过滤状态 (all, downloading, seeding, completed, paused, active, etc.)
        """
        self._ensure_auth()

        params = {}
        if filter_status:
            params["filter"] = filter_status

        try:
            resp = self.client.get("/api/v2/torrents/info", params=params)
            return resp.json()
        except Exception as e:
            logger.error(f"获取种子列表失败: {e}")
            return []

    def get_torrent_by_hash(self, info_hash: str) -> Optional[Dict]:
        """根据 info hash 获取种子信息"""
        torrents = self.get_all_torrents()
        for t in torrents:
            if t.get("hash", "").upper() == info_hash.upper():
                return t
        return None

    def get_torrent_status(self, info_hash: str) -> Optional[Dict]:
        """
        获取单个种子状态
        Returns: {"state": "...", "progress": 0.85, "ratio": 1.5, ...}
        """
        t = self.get_torrent_by_hash(info_hash)
        if not t:
            return None

        return {
            "name": t.get("name", ""),
            "hash": t.get("hash", ""),
            "state": t.get("state", ""),
            "progress": t.get("progress", 0),
            "size": t.get("size", 0),
            "downloaded": t.get("downloaded", 0),
            "ratio": t.get("ratio", 0),
            "seeding_time_hours": t.get("seeding_time", 0) / 3600 if t.get("seeding_time") else 0,
            "save_path": t.get("save_path", ""),
            "content_path": t.get("content_path", ""),
            "category": t.get("category", ""),
            "added_on": t.get("added_on", 0),
            "completion_on": t.get("completion_on", 0),
        }

    def get_seeding_torrents(self) -> List[Dict]:
        """获取所有做种中的种子"""
        return self.get_all_torrents(filter_status="seeding")

    def get_completed_torrents(self) -> List[Dict]:
        """获取所有已完成的种子"""
        return self.get_all_torrents(filter_status="completed")

    # ================================================================
    # 删除操作
    # ================================================================

    def delete_torrents(self, hashes: List[str], delete_files: bool = False) -> bool:
        """
        删除种子

        Args:
            hashes: info hash 列表
            delete_files: 是否同时删除下载文件
        """
        self._ensure_auth()

        if not hashes:
            return True

        data = {
            "hashes": "|".join(hashes),
            "deleteFiles": str(delete_files).lower(),
        }

        try:
            resp = self.client.post("/api/v2/torrents/delete", data=data)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"删除种子失败: {e}")
            return False

    def pause_torrents(self, hashes: List[str]) -> bool:
        """暂停种子"""
        self._ensure_auth()
        try:
            resp = self.client.post(
                "/api/v2/torrents/pause",
                data={"hashes": "|".join(hashes)},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"暂停种子失败: {e}")
            return False

    def resume_torrents(self, hashes: List[str]) -> bool:
        """恢复种子"""
        self._ensure_auth()
        try:
            resp = self.client.post(
                "/api/v2/torrents/resume",
                data={"hashes": "|".join(hashes)},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"恢复种子失败: {e}")
            return False


# 全局单例
_qb: Optional[QBitManager] = None


def get_qb() -> QBitManager:
    global _qb
    if _qb is None:
        _qb = QBitManager()
    return _qb
