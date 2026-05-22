"""
做种管理模块（新架构）
- 监控做种状态
- 达标后删除 qBittorrent 任务（自动清理 Temp 文件）
- 通知用户

达标条件：比率 >= min_ratio 且 做种时长 >= min_seeding_time_hours
默认：比率 2.0，时长 24 小时
"""

import logging
from pathlib import Path
from typing import Dict, List

import config, db
from qb_manager import get_qb
from notifier import get_notifier

logger = logging.getLogger(__name__)


def _clean_temp_dir(temp_path: str, base_temp: str):
    """
    清理 Temp 目录中已下载的文件
    如果 qB 删除文件时没清干净，手动补刀

    Args:
        temp_path: 要清理的路径（由 qB content_path 推断）
        base_temp: Temp 根目录
    """
    try:
        cp = Path(temp_path)
        if not cp.exists():
            return

        # 如果是 Temp 下的子目录，尝试删除
        base = Path(base_temp)
        try:
            cp.relative_to(base)
        except ValueError:
            # 不在 Temp 下，跳过
            return

        if cp.is_dir():
            # 删除整个目录
            import shutil
            shutil.rmtree(cp, ignore_errors=True)
            logger.info(f"手动清理 Temp 目录: {cp}")
        elif cp.is_file():
            cp.unlink(missing_ok=True)
            logger.info(f"手动清理 Temp 文件: {cp}")
    except Exception as e:
        logger.warning(f"清理 Temp 时异常: {e}")


def check_and_clean_seeds() -> Dict:
    """
    检查所有做种任务，达标则清理

    Returns:
        {"checked": 50, "cleaned": 3, "errors": [...]}
    """
    result = {"checked": 0, "cleaned": 0, "errors": []}

    qb = get_qb()
    notifier = get_notifier()
    seeding_cfg = config.get_seeding_config()
    min_ratio = seeding_cfg.get("min_ratio", 2.0)
    min_hours = seeding_cfg.get("min_seeding_time_hours", 24)  # 默认 24 小时
    dirs = config.get_directories()
    base_temp = dirs.get("temp", "/volume1/Temp")

    # 获取所有做种中的种子
    seeding = qb.get_seeding_torrents()
    result["checked"] = len(seeding)

    for t in seeding:
        info_hash = t.get("hash", "").upper()
        ratio = t.get("ratio", 0)
        seeding_time = t.get("seeding_time", 0) / 3600  # 秒转小时
        name = t.get("name", "")
        content_path = t.get("content_path", "")

        # 更新做种统计到数据库
        db.update_seeding_stats(info_hash, ratio, seeding_time)

        # 检查是否达标
        if ratio >= min_ratio and seeding_time >= min_hours:
            logger.info(f"做种达标: {name} (ratio={ratio:.2f}, hours={seeding_time:.1f})")

            # 查找下载记录
            conn = db.get_connection()
            row = conn.execute(
                "SELECT dh.id, dh.episode, at.title_cn "
                "FROM download_history dh "
                "JOIN anime_tracking at ON dh.anime_id = at.id "
                "WHERE dh.torrent_hash = ? AND dh.seed_cleaned = 0",
                (info_hash,)
            ).fetchone()
            conn.close()

            if row:
                # 🗑️ 删除 qBittorrent 中的种子（同时删除 Temp 文件）
                qb.delete_torrents([t.get("hash", "")], delete_files=True)
                db.mark_seed_cleaned(row["id"])

                # 补刀：确保 Temp 文件被清干净
                _clean_temp_dir(content_path, base_temp)

                notifier.notify_seed_cleanup(
                    row["title_cn"] or name,
                    row["episode"],
                    ratio,
                )
                result["cleaned"] += 1
                logger.info(f"已清理做种+Temp: {name}")

    logger.info(f"做种检查完成: checked={result['checked']}, cleaned={result['cleaned']}")
    return result


def get_seeding_status() -> List[Dict]:
    """获取当前做种状态（供 API 查询）"""
    qb = get_qb()
    seeding = qb.get_seeding_torrents()

    status_list = []
    for t in seeding:
        status_list.append({
            "name": t.get("name", ""),
            "hash": t.get("hash", ""),
            "ratio": t.get("ratio", 0),
            "seeding_hours": t.get("seeding_time", 0) / 3600,
            "size": t.get("size", 0),
            "state": t.get("state", ""),
            "category": t.get("category", ""),
        })

    return status_list
