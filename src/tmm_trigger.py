"""
TMM (TinyMediaManager) HTTP API 触发模块
- 触发 TMM 刮削（update → scrape → rename）
- 仅走 HTTP API，不 SSH/docker exec

TMM HTTP API 文档: https://www.tinymediamanager.org/docs/http-api
"""

import logging
from typing import Optional, List, Dict

import httpx

import config

logger = logging.getLogger(__name__)


class TMMTrigger:
    """TMM HTTP API 客户端"""

    def __init__(self):
        cfg = config.get_tmm_config()
        self.api_url = cfg.get("api_url", "http://localhost:7878").rstrip("/")
        self.api_key = cfg.get("api_key", "")

        if not self.api_key:
            logger.warning("TMM API Key 未配置！请设置 TMM_API_KEY 环境变量")

        self.headers = {
            "api-key": self.api_key,
        }
        self.client = httpx.Client(
            base_url=self.api_url,
            headers=self.headers,
            timeout=60.0,
        )

    def close(self):
        self.client.close()

    # ================================================================
    # TV Show 操作
    # ================================================================

    def trigger_update(self, path: str = None) -> bool:
        """
        触发 TMM 更新媒体库
        POST /api/tvshow/update

        Args:
            path: 要更新的目录路径，不传则更新所有
        """
        try:
            data = {}
            if path:
                data["path"] = path

            resp = self.client.post("/api/tvshow/update", json=data)
            logger.info(f"TMM update 触发成功: {resp.status_code}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"TMM update 触发失败: {e}")
            return False

    def trigger_scrape(self, path: str = None,
                       scope: str = None) -> bool:
        """
        触发 TMM 刮削
        POST /api/tvshow/scrape

        Args:
            path: 要刮削的目录路径
            scope: 保留参数但不再使用（TMM API 不支持 string scope）
        """
        try:
            data = {}
            if path:
                data["path"] = path

            resp = self.client.post("/api/tvshow/scrape", json=data)
            logger.info(f"TMM scrape 触发成功: {resp.status_code}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"TMM scrape 触发失败: {e}")
            return False

    def trigger_rename(self, path: str = None,
                       scope: str = None) -> bool:
        """
        触发 TMM 重命名
        POST /api/tvshow/rename

        Args:
            path: 要重命名的目录路径
            scope: 保留参数但不再使用
        """
        try:
            data = {}
            if path:
                data["path"] = path

            resp = self.client.post("/api/tvshow/rename", json=data)
            logger.info(f"TMM rename 触发成功: {resp.status_code}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"TMM rename 触发失败: {e}")
            return False

    def trigger_full_scrape(self, anime_id: int = None,
                            title_cn: str = None) -> Dict:
        """
        触发完整刮削流程: update → scrape → rename
        遵循 TMM 现有配置策略

        Args:
            anime_id: 番剧 ID（日志用）
            title_cn: 番剧中文名

        Returns:
            {"success": True/False, "steps": [...], "error": None/msg}
        """
        result = {
            "success": True,
            "steps": [],
            "error": None,
        }

        prefix = f"[{title_cn or anime_id}]"

        # Step 1: UPDATE
        logger.info(f"{prefix} 触发 TMM update...")
        ok = self.trigger_update()
        result["steps"].append({"step": "update", "ok": ok})
        if not ok:
            result["error"] = "TMM update 失败"
            result["success"] = False
            return result

        # Step 2: SCRAPE (仅新品)
        logger.info(f"{prefix} 触发 TMM scrape (new)...")
        ok = self.trigger_scrape(scope="new")
        result["steps"].append({"step": "scrape", "ok": ok})
        if not ok:
            result["error"] = "TMM scrape 失败"
            result["success"] = False
            return result

        # Step 3: RENAME (仅新品)
        logger.info(f"{prefix} 触发 TMM rename (new)...")
        ok = self.trigger_rename(scope="new")
        result["steps"].append({"step": "rename", "ok": ok})
        if not ok:
            result["error"] = "TMM rename 失败"
            result["success"] = False
            return result

        logger.info(f"{prefix} TMM 完整刮削流程完成")
        return result

    # ================================================================
    # 健康检查
    # ================================================================

    def check_health(self) -> bool:
        """检查 TMM HTTP API 是否可用（调 /api/tvshow 验证）"""
        try:
            # TMM 没有 /api/health 端点，用 /api/tvshow 验证连通性
            resp = self.client.get("/api/tvshow", timeout=5.0)
            # 200=有数据, 500=无数据但服务正常, 403=key错误
            return resp.status_code in (200, 500)
        except Exception:
            return False


# 全局单例
_tmm: Optional[TMMTrigger] = None


def get_tmm() -> TMMTrigger:
    global _tmm
    if _tmm is None:
        _tmm = TMMTrigger()
    return _tmm
