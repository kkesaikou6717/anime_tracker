"""
定时调度模块 (APScheduler)
- 每小时搜索种子
- 每晚 20:00 日报
- 每 12 小时检查做种状态
- 季度归档检查
"""

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import config, db
from bangumi import get_bangumi
from dmhy_search import get_dmhy
from qb_manager import get_qb
from tmm_trigger import get_tmm
from notifier import get_notifier
from seed_manager import check_and_clean_seeds
from archive_manager import check_and_archive


# ================================================================
# 文件操作辅助
# ================================================================

def _copy_to_anime(src_path: str, title_cn: str, anime_dir: str) -> str:
    """
    将文件从临时下载目录复制到最终 Anime 目录

    Args:
        src_path: 源路径（qB content_path）
        title_cn: 番剧中文名
        anime_dir: Anime 根目录

    Returns:
        目标目录路径

    Raises:
        FileNotFoundError: 源文件不存在
        shutil.Error: 复制失败
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"源文件不存在: {src_path}")

    dst_dir = Path(anime_dir) / _sanitize_dirname(title_cn)
    dst_dir.mkdir(parents=True, exist_ok=True)

    if src.is_file():
        # 单文件种子
        dst = dst_dir / src.name
        shutil.copy2(str(src), str(dst))
        logger.info(f"复制文件: {src} → {dst}")
    else:
        # 多文件种子（目录）— 复制目录内所有文件
        for item in src.iterdir():
            dst_item = dst_dir / item.name
            if item.is_file():
                if dst_item.exists():
                    logger.warning(f"目标已存在，跳过: {dst_item}")
                    continue
                shutil.copy2(str(item), str(dst_item))
                logger.info(f"复制文件: {item.name} → {dst_item}")
            elif item.is_dir():
                # Season XX 子目录
                _copy_tree(item, dst_dir / item.name)

    logger.info(f"复制完成: {title_cn} → {dst_dir}")
    return str(dst_dir)


def _copy_tree(src: Path, dst: Path):
    """递归复制目录树"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dst_item = dst / item.name
        if item.is_file():
            if dst_item.exists():
                continue
            shutil.copy2(str(item), str(dst_item))
        elif item.is_dir():
            _copy_tree(item, dst_item)


def _sanitize_dirname(name: str) -> str:
    """清理目录名中的非法字符"""
    # 只保留常见合法字符，替换空格和特殊符号
    import re
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = name.strip()
    return name if name else "Unknown"


def _get_temp_cleanup_path(content_path: str, base_temp: str) -> str:
    """
    从 qB content_path 推断 Temp 中需要清理的路径
    qB 下载到 /volume1/Temp/AnimeName/  -> 清理 /volume1/Temp/AnimeName/
    """
    cp = Path(content_path)
    base = Path(base_temp)
    # 如果 content_path 在 temp 目录下，取其根目录
    try:
        rel = cp.relative_to(base)
        parts = rel.parts
        if parts:
            # 返回 Temp/{第一级子目录}
            return str(base / parts[0])
    except ValueError:
        pass
    return str(cp)

logger = logging.getLogger(__name__)

TZ_SHANGHAI = timezone(timedelta(hours=8))

_scheduler: BackgroundScheduler = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={
                "coalesce": True,      # 合并错过的任务
                "max_instances": 1,    # 同一作业最多1个实例
                "misfire_grace_time": 300,  # 错过5分钟内仍执行
            },
        )
    return _scheduler


# ================================================================
# 定时任务
# ================================================================

def job_search_new_episodes():
    """
    每小时搜索任务：
    1. 读取追番列表
    2. 逐个搜索最新集
    3. 自动下载新集
    """
    logger.info("=" * 50)
    logger.info("[定时任务] 开始搜索新集...")

    tracking_list = db.get_tracking_list(status="ongoing")
    if not tracking_list:
        logger.info("暂无进行中的追番")
        return

    dmhy = get_dmhy()
    qb = get_qb()
    notifier = get_notifier()

    found_new = 0
    directories = config.get_directories()
    download_dir = directories.get("download", "/volume1/Video/Download")

    for anime in tracking_list:
        anime_id = anime["id"]
        title_cn = anime["title_cn"]
        preferred_group = anime.get("sub_group", "")

        # 获取已下载的集数
        downloaded = db.get_downloaded_episodes(anime_id)
        max_downloaded = max(downloaded) if downloaded else 0

        # 搜索下一集
        next_ep = max_downloaded + 1

        # 如果已知总集数，检查是否已完结
        total = anime.get("total_episodes", 0)
        if total and max_downloaded >= total:
            logger.info(f"[{title_cn}] 已完结 ({max_downloaded}/{total})")
            continue

        result = dmhy.search_anime_episode(
            title_cn=title_cn,
            episode=next_ep,
            preferred_sub_group=preferred_group,
            resolution="1080p",
        )

        if not result:
            # 尝试搜索 max_downloaded + 1 ~ max_downloaded + 3
            # 可能错过了一集
            for ep in range(next_ep + 1, next_ep + 4):
                result = dmhy.search_anime_episode(
                    title_cn=title_cn,
                    episode=ep,
                    preferred_sub_group=preferred_group,
                    resolution="1080p",
                )
                if result:
                    next_ep = ep
                    break

        if not result:
            logger.info(f"[{title_cn}] 未找到新集 (搜至 EP{next_ep + 3})")
            continue

        # 防重复检查
        if db.is_episode_downloaded(anime_id, next_ep):
            logger.info(f"[{title_cn}] EP{next_ep} 已下载，跳过")
            continue

        # 字幕组降级检查
        actual_group = result.get("matched_group", "")
        if preferred_group and actual_group and preferred_group not in actual_group:
            db.log_sub_fallback(anime_id, next_ep, preferred_group, actual_group)
            if config.get_tracker_config().get("notify_on_sub_fallback", True):
                notifier.notify_sub_fallback(title_cn, next_ep, preferred_group, actual_group)

        # 添加下载
        magnet = result.get("magnet", "") or result.get("torrent_url", "")
        if not magnet:
            logger.warning(f"[{title_cn}] EP{next_ep} 无磁力链接")
            continue

        if qb.add_torrent(magnet, save_path=f"{download_dir}/{title_cn}"):
            # 记录下载
            db.insert_download({
                "anime_id": anime_id,
                "episode": next_ep,
                "sub_group": actual_group or preferred_group,
                "torrent_hash": result.get("info_hash", ""),
                "torrent_title": result.get("title", ""),
                "status": "downloading",
            })

            notifier.notify_new_episode(title_cn, next_ep, actual_group or preferred_group)
            found_new += 1
            logger.info(f"[{title_cn}] EP{next_ep} 已加入下载队列")
        else:
            logger.error(f"[{title_cn}] EP{next_ep} 添加下载失败")

    logger.info(f"[定时任务] 搜索完成，新增 {found_new} 个下载")
    logger.info("=" * 50)


def job_daily_report():
    """每晚 20:00 日报"""
    logger.info("[定时任务] 生成日报...")

    notifier = get_notifier()
    stats = db.get_today_stats()
    tracking = db.get_tracking_list(status="ongoing")
    recent = db.get_recent_downloads(limit=20)

    stats["tracking_count"] = len(tracking)

    report = {
        "stats": stats,
        "tracking": tracking,
        "recent_downloads": recent,
    }

    notifier.send_daily_report(report)
    logger.info(f"[定时任务] 日报发送完成: {stats}")


def job_seed_check():
    """每12小时检查做种状态"""
    logger.info("[定时任务] 检查做种状态...")
    result = check_and_clean_seeds()
    logger.info(f"[定时任务] 做种检查完成: {result}")


def job_archive_check():
    """每周检查是否需要季度归档"""
    logger.info("[定时任务] 检查归档状态...")
    result = check_and_archive()
    if result.get("action"):
        logger.info(f"[定时任务] 归档操作: {result}")


def job_download_monitor():
    """每10分钟检查下载状态 → 复制到 Anime → 触发刮削"""
    logger.debug("[定时任务] 检查下载进度...")

    qb = get_qb()
    tmm = get_tmm()
    notifier = get_notifier()
    dirs = config.get_directories()
    anime_dir = dirs.get("anime", "/volume1/Video/已归档/Anime")

    # 获取所有下载中/完成的种子
    torrents = qb.get_all_torrents()

    for t in torrents:
        info_hash = t.get("hash", "")
        state = t.get("state", "")
        name = t.get("name", "")
        content_path = t.get("content_path", "")

        if state in ("uploading", "stalledUP"):
            # 已完成，查找对应的下载记录
            conn = db.get_connection()
            row = conn.execute(
                "SELECT dh.*, at.title_cn FROM download_history dh "
                "JOIN anime_tracking at ON dh.anime_id = at.id "
                "WHERE dh.torrent_hash = ? AND dh.scraped = 0 "
                "AND (dh.status = 'downloading' OR dh.status = 'pending')",
                (info_hash.upper(),)
            ).fetchone()
            conn.close()

            if row:
                dh = dict(row)
                title_cn = dh.get("title_cn", name)
                episode = dh.get("episode", 0)

                # 1️⃣ 更新下载状态为 completed
                db.update_download_status(
                    torrent_hash=info_hash.upper(),
                    status="completed",
                    file_path=content_path,
                )
                notifier.notify_download_complete(title_cn, episode)

                # 2️⃣ 从 Temp 复制到 Anime 目录
                dst_path = None
                try:
                    dst_path = _copy_to_anime(
                        src_path=content_path,
                        title_cn=title_cn,
                        anime_dir=anime_dir,
                    )
                except Exception as e:
                    logger.error(f"文件复制失败 [{title_cn} EP{episode}]: {e}")
                    notifier.notify_error(title_cn, f"文件复制失败: {e}")
                    continue

                # 3️⃣ 触发 TMM 刮削（scope=new 只刮新品）
                tmm_result = tmm.trigger_full_scrape()

                if tmm_result.get("success"):
                    db.update_download_status(
                        torrent_hash=info_hash.upper(),
                        scraped=True,
                    )
                    notifier.notify_scrape_complete(
                        title_cn, episode,
                        dest_path=str(dst_path),
                    )
                else:
                    logger.error(f"TMM 刮削失败 [{title_cn} EP{episode}]: "
                                 f"{tmm_result.get('error', '未知错误')}")
                    notifier.notify_error(
                        title_cn,
                        f"EP{episode} TMM 刮削失败: {tmm_result.get('error', '未知错误')}"
                    )


# ================================================================
# 调度器管理
# ================================================================

def setup_scheduler():
    """配置并启动所有定时任务"""
    scheduler = get_scheduler()
    sched_cfg = config.get_schedule_config()

    # 每小时搜索新集
    interval = sched_cfg.get("search_interval_minutes", 60)
    scheduler.add_job(
        job_search_new_episodes,
        IntervalTrigger(minutes=interval, timezone=TZ_SHANGHAI),
        id="search_new_episodes",
        name="搜索新集",
        replace_existing=True,
    )

    # 每晚 20:00 日报
    report_time = sched_cfg.get("daily_report_time", "20:00")
    hour, minute = report_time.split(":")
    scheduler.add_job(
        job_daily_report,
        CronTrigger(hour=int(hour), minute=int(minute), timezone=TZ_SHANGHAI),
        id="daily_report",
        name="日报",
        replace_existing=True,
    )

    # 每12小时做种检查
    seed_interval = sched_cfg.get("seed_check_interval_minutes", 720)
    scheduler.add_job(
        job_seed_check,
        IntervalTrigger(minutes=seed_interval, timezone=TZ_SHANGHAI),
        id="seed_check",
        name="做种检查",
        replace_existing=True,
    )

    # 每周归档检查（周日凌晨 3:00）
    scheduler.add_job(
        job_archive_check,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=TZ_SHANGHAI),
        id="archive_check",
        name="归档检查",
        replace_existing=True,
    )

    # 每10分钟下载进度监控
    scheduler.add_job(
        job_download_monitor,
        IntervalTrigger(minutes=10, timezone=TZ_SHANGHAI),
        id="download_monitor",
        name="下载监控",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("定时调度器已启动")
    _print_jobs(scheduler)


def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("定时调度器已停止")


def _print_jobs(scheduler: BackgroundScheduler):
    """打印已注册的定时任务"""
    jobs = scheduler.get_jobs()
    logger.info("已注册定时任务:")
    for job in jobs:
        logger.info(f"  • {job.name} ({job.id}): {job.next_run_time}")


def trigger_search_now():
    """手动触发搜索（供 API 调用）"""
    logger.info("手动触发搜索...")
    job_search_new_episodes()


def trigger_report_now():
    """手动触发日报（供 API 调用）"""
    logger.info("手动触发日报...")
    job_daily_report()


def job_retry_unscraped():
    """
    重新处理已下载但未刮削的文件
    用于迁移期：将旧路径已完成的文件复制到 Anime 并触发刮削
    """
    logger.info("重试未刮削的已完成下载...")

    # 从数据库获取 scraped=0, status=completed 的记录
    unscraped = db.get_pending_scrape()
    if not unscraped:
        logger.info("没有待处理的未刮削记录")
        return {"found": 0, "copied": 0, "scraped": 0, "errors": []}

    qb = get_qb()
    tmm = get_tmm()
    notifier = get_notifier()
    dirs = config.get_directories()
    anime_dir = dirs.get("anime", "/volume1/Video/已归档/Anime")

    result = {"found": len(unscraped), "copied": 0, "scraped": 0, "errors": []}

    for dh in unscraped:
        title_cn = dh.get("title_cn", "Unknown")
        episode = dh.get("episode", 0)
        torchash = dh.get("torrent_hash", "")

        # 尝试从 qB 获取 content_path
        content_path = dh.get("file_path", "")
        if torchash:
            t = qb.get_torrent_by_hash(torchash)
            if t:
                content_path = t.get("content_path", content_path)

        if not content_path or not Path(content_path).exists():
            logger.warning(f"文件不存在，跳过: {content_path} [{title_cn} EP{episode}]")
            result["errors"].append(f"{title_cn} EP{episode}: 文件不存在")
            continue

        # 复制到 Anime/
        try:
            dst_path = _copy_to_anime(
                src_path=content_path,
                title_cn=title_cn,
                anime_dir=anime_dir,
            )
            result["copied"] += 1
            logger.info(f"复制完成: {title_cn} EP{episode} → {dst_path}")
        except Exception as e:
            logger.error(f"复制失败 [{title_cn} EP{episode}]: {e}")
            result["errors"].append(f"{title_cn} EP{episode}: 复制失败 - {e}")
            continue

        # 触发 TMM 刮削
        tmm_result = tmm.trigger_full_scrape()

        if tmm_result.get("success"):
            if torchash:
                db.update_download_status(torrent_hash=torchash.upper(), scraped=True)
            else:
                db.update_download_status(download_id=dh["id"], scraped=True)
            result["scraped"] += 1
            notifier.notify_scrape_complete(
                title_cn, episode,
                dest_path=str(dst_path),
            )
            logger.info(f"刮削完成: {title_cn} EP{episode}")
        else:
            err = tmm_result.get("error", "未知错误")
            logger.error(f"刮削失败 [{title_cn} EP{episode}]: {err}")
            result["errors"].append(f"{title_cn} EP{episode}: 刮削失败 - {err}")

    logger.info(f"重试完成: found={result['found']}, "
                 f"copied={result['copied']}, "
                 f"scraped={result['scraped']}")
    return result


def trigger_retry_unscraped():
    """手动触发未刮削重试（供 API 调用）"""
    logger.info("手动触发未刮削重试...")
    return job_retry_unscraped()
