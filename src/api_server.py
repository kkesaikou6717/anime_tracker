"""
REST API 服务 — FastAPI
提供 10 个接口供 OpenClaw Skill 调用

接口列表：
  GET  /api/health            — 健康检查
  GET  /api/season/current    — 获取当季新番列表
  POST /api/tracking/save     — 保存追番列表
  GET  /api/tracking/list     — 获取当前追番列表
  POST /api/search            — 搜索指定番剧的种子
  POST /api/download          — 导入指定种子到 qBittorrent
  GET  /api/status/daily      — 获取今日执行摘要
  GET  /api/status/seed       — 获取做种状态
  POST /api/archive/trigger   — 触发季度归档
  POST /api/notify/test       — 测试 Server酱 通知
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config, db
from bangumi import get_bangumi
from dmhy_search import get_dmhy
from qb_manager import get_qb
from tmm_trigger import get_tmm
from notifier import get_notifier
from init_scanner import run_scan
from scheduler import trigger_search_now, trigger_report_now, trigger_retry_unscraped
from seed_manager import check_and_clean_seeds, get_seeding_status
from archive_manager import trigger_manual_archive
from multi_season import check_and_setup_multi_season

logger = logging.getLogger(__name__)

TZ_SHANGHAI = timezone(timedelta(hours=8))

app = FastAPI(
    title="Anime Tracker API",
    description="自动化追番系统 — Python 后端服务",
    version="1.0.0",
)

# 允许跨域（内网使用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================
# Pydantic Models
# ================================================================

class TrackingSaveRequest(BaseModel):
    season: str
    animes: List[dict]


class SearchRequest(BaseModel):
    keyword: str
    sub_group: Optional[str] = None
    resolution: str = "1080p"


class DownloadRequest(BaseModel):
    magnet: str
    anime_id: int
    episode: int
    sub_group: Optional[str] = None
    torrent_hash: Optional[str] = None
    torrent_title: Optional[str] = None


class ScanRequest(BaseModel):
    full: bool = False


# ================================================================
# API Endpoints
# ================================================================

@app.get("/api/health")
def health_check():
    """1. 健康检查"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(TZ_SHANGHAI).isoformat(),
        "services": {
            "database": _check_db(),
            "bangumi": _check_bangumi(),
            "dmhy": _check_dmhy(),
            "qbittorrent": _check_qb(),
            "tmm": _check_tmm(),
            "notifier": _check_notifier(),
        }
    }


@app.get("/api/season/current")
def get_current_season(season: Optional[str] = None):
    """
    2. 获取当季新番列表
    Args:
        season: 可选，指定季度如 '2026-07'
    """
    bangumi = get_bangumi()
    anime_list = bangumi.get_season_anime(season)

    return {
        "season": season or bangumi.get_current_season(),
        "count": len(anime_list),
        "animes": anime_list,
    }


@app.post("/api/tracking/save")
def save_tracking_list(req: TrackingSaveRequest):
    """
    3. 保存追番列表
    接收 OpenClaw Skill 选定的追番列表
    """
    saved = []
    errors = []

    for anime in req.animes:
        try:
            anime["season"] = req.season
            anime_id = db.upsert_tracking(anime)

            # 多季检查
            series_id = anime.get("series_id")
            if series_id:
                check_and_setup_multi_season(
                    anime.get("bangumi_id"),
                    series_id,
                    anime.get("title_cn", ""),
                )

            saved.append({
                "title_cn": anime.get("title_cn"),
                "anime_id": anime_id,
                "sub_group": anime.get("sub_group"),
            })
        except Exception as e:
            logger.error(f"保存追番失败: {anime.get('title_cn')}: {e}")
            errors.append({"title_cn": anime.get("title_cn"), "error": str(e)})

    return {
        "saved": len(saved),
        "errors": len(errors),
        "items": saved,
        "error_details": errors if errors else None,
    }


@app.get("/api/tracking/list")
def get_tracking_list(status: Optional[str] = None):
    """
    4. 获取当前追番列表
    Args:
        status: 可选过滤 (ongoing/finished/archived)
    """
    tracking = db.get_tracking_list(status=status)

    # 附加每部番的下载进度
    result = []
    for t in tracking:
        episodes = db.get_downloaded_episodes(t["id"])
        t["downloaded_episodes"] = episodes
        t["downloaded_count"] = len(episodes)
        result.append(dict(t))

    return {
        "total": len(result),
        "tracking": result,
    }


@app.post("/api/search")
def search_anime(req: SearchRequest):
    """
    5. 搜索指定番剧的种子
    """
    dmhy = get_dmhy()
    results = dmhy.search(
        keyword=req.keyword,
        sub_group=req.sub_group,
        resolution=req.resolution,
    )

    return {
        "keyword": req.keyword,
        "count": len(results),
        "results": results[:20],  # 最多返回20条
    }


@app.post("/api/download")
def download_torrent(req: DownloadRequest):
    """
    6. 导入指定种子到 qBittorrent
    """
    # 防重复检查
    if db.is_episode_downloaded(req.anime_id, req.episode):
        raise HTTPException(status_code=409, detail="该集已下载过")

    qb = get_qb()
    success = qb.add_torrent(req.magnet)

    if success:
        # 记录下载
        db.insert_download({
            "anime_id": req.anime_id,
            "episode": req.episode,
            "sub_group": req.sub_group,
            "torrent_hash": req.torrent_hash,
            "torrent_title": req.torrent_title,
            "status": "downloading",
        })

        return {
            "success": True,
            "message": f"已添加下载: anime_id={req.anime_id} EP{req.episode}",
        }
    else:
        raise HTTPException(status_code=500, detail="添加下载失败")


@app.get("/api/status/daily")
def get_daily_status():
    """
    7. 获取今日执行摘要
    """
    stats = db.get_today_stats()
    tracking = db.get_tracking_list(status="ongoing")
    recent = db.get_recent_downloads(limit=20)

    return {
        "date": stats.get("date"),
        "stats": {
            "today_downloaded": stats.get("downloaded", 0),
            "today_scraped": stats.get("scraped", 0),
            "seeding": stats.get("seeding", 0),
            "tracking_count": len(tracking),
        },
        "tracking": [
            {
                "title_cn": t["title_cn"],
                "sub_group": t.get("sub_group"),
                "downloaded": len(db.get_downloaded_episodes(t["id"])),
                "total": t.get("total_episodes", "?"),
                "status": t.get("status"),
            }
            for t in tracking
        ],
        "recent_downloads": [
            {
                "title_cn": d.get("title_cn"),
                "episode": d.get("episode"),
                "status": d.get("status"),
                "scraped": d.get("scraped"),
                "downloaded_at": d.get("downloaded_at"),
            }
            for d in recent[:10]
        ],
    }


@app.get("/api/status/seed")
def get_seed_status():
    """
    8. 获取做种状态
    """
    status_list = get_seeding_status()
    cleanable = db.get_seeding_cleanable()

    return {
        "total_seeding": len(status_list),
        "seeding": status_list,
        "cleanable_count": len(cleanable),
        "cleanable": [
            {
                "title": c.get("torrent_title", ""),
                "episode": c.get("episode"),
                "ratio": c.get("seeding_ratio"),
                "hours": c.get("seeding_hours"),
            }
            for c in cleanable
        ],
    }


@app.post("/api/archive/trigger")
def trigger_archive():
    """
    9. 触发季度归档
    """
    result = trigger_manual_archive()
    return result


@app.post("/api/notify/test")
def test_notification():
    """
    10. 测试 Server酱 通知
    """
    notifier = get_notifier()
    ok = notifier._send(
        title="🧪 Anime Tracker 测试通知",
        content=f"测试时间: {datetime.now(TZ_SHANGHAI).isoformat()}\n"
                f"如果你收到这条消息，说明 Server酱 通知配置成功！"
    )
    return {"success": ok, "message": "通知已发送" if ok else "通知发送失败"}


# ================================================================
# 额外便捷接口（非10个标准接口，但好用）
# ================================================================

@app.post("/api/scan/trigger")
def trigger_scan(req: ScanRequest = ScanRequest()):
    """触发已有动漫扫描"""
    result = run_scan(full=req.full)
    return result


@app.post("/api/search/trigger")
def trigger_manual_search():
    """手动触发搜索"""
    trigger_search_now()
    return {"message": "搜索已触发"}


@app.post("/api/report/trigger")
def trigger_manual_report():
    """手动触发日报"""
    trigger_report_now()
    return {"message": "日报已触发"}


@app.post("/api/retry/unscraped")
def api_retry_unscraped():
    """
    重新处理已下载但未刮削的文件
    用于迁移期：将旧路径的文件复制到 Anime/ 并触发 TMM 刮削
    """
    result = trigger_retry_unscraped()
    return result


# ================================================================
# 服务检查辅助函数
# ================================================================

def _check_db() -> str:
    try:
        conn = db.get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return "ok"
    except Exception as e:
        return f"error: {e}"


def _check_bangumi() -> str:
    return "ok"  # 不实际请求，避免频繁调用


def _check_dmhy() -> str:
    return "ok"


def _check_qb() -> str:
    try:
        qb = get_qb()
        qb._ensure_auth()
        return "ok"
    except Exception as e:
        return f"error: {e}"


def _check_tmm() -> str:
    try:
        tmm = get_tmm()
        if tmm.check_health():
            return "ok"
        return "unreachable"
    except Exception as e:
        return f"error: {e}"


def _check_notifier() -> str:
    notifier = get_notifier()
    return "ok" if notifier.enabled else "disabled (no sendkey)"
