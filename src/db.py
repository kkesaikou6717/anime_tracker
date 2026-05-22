"""
SQLite 数据库模块
- 3张表：anime_tracking / download_history / sub_group_fallback_log
- CRUD 操作
- 防重复查询
"""

import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# 东八区时区
TZ_SHANGHAI = timezone(timedelta(hours=8))

# 数据库路径
DB_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DB_DIR / "anime_tracker.db"


def get_db_path() -> str:
    """获取数据库文件路径，确保目录存在"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    # Docker 环境下使用 /app/data/
    docker_path = Path("/app/data/anime_tracker.db")
    if docker_path.parent.exists():
        return str(docker_path)
    return str(DB_PATH)


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（WAL模式，外键开启）"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    """返回当前东八区 ISO 时间字符串"""
    return datetime.now(TZ_SHANGHAI).isoformat()


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    cursor = conn.cursor()

    # ===== anime_tracking — 追番列表 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anime_tracking (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bangumi_id      INTEGER,
            series_id       INTEGER,
            title_cn        TEXT NOT NULL,
            title_jp        TEXT,
            season          TEXT NOT NULL,
            season_number   INTEGER DEFAULT 1,
            sub_group       TEXT,
            resolution      TEXT DEFAULT '1080p',
            total_episodes  INTEGER,
            status          TEXT DEFAULT 'ongoing',
            created_at      DATETIME DEFAULT (datetime('now', 'localtime')),
            updated_at      DATETIME DEFAULT (datetime('now', 'localtime')),
            UNIQUE(bangumi_id, season)
        )
    """)

    # ===== download_history — 下载历史 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS download_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_id        INTEGER NOT NULL,
            episode         INTEGER NOT NULL,
            sub_group       TEXT,
            torrent_hash    TEXT,
            torrent_title   TEXT,
            file_path       TEXT,
            file_size       INTEGER,
            status          TEXT DEFAULT 'pending',
            downloaded_at   DATETIME,
            scraped         BOOLEAN DEFAULT 0,
            scraped_at      DATETIME,
            seeding_ratio   REAL DEFAULT 0,
            seeding_hours   REAL DEFAULT 0,
            seed_cleaned    BOOLEAN DEFAULT 0,
            FOREIGN KEY (anime_id) REFERENCES anime_tracking(id),
            UNIQUE(anime_id, episode)
        )
    """)

    # ===== sub_group_fallback_log — 字幕组降级日志 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sub_group_fallback_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_id         INTEGER NOT NULL,
            episode          INTEGER NOT NULL,
            preferred_group  TEXT NOT NULL,
            actual_group     TEXT NOT NULL,
            notified         BOOLEAN DEFAULT 0,
            created_at       DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (anime_id) REFERENCES anime_tracking(id)
        )
    """)

    # ===== 索引 =====
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_download_anime_ep
        ON download_history(anime_id, episode)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_download_torrent_hash
        ON download_history(torrent_hash)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_download_scraped
        ON download_history(scraped, downloaded_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_download_seed
        ON download_history(seed_cleaned, seeding_ratio, seeding_hours)
    """)

    conn.commit()
    conn.close()
    logger.info(f"数据库初始化完成: {get_db_path()}")


# ============================================================
# anime_tracking CRUD
# ============================================================

def upsert_tracking(anime: Dict[str, Any]) -> int:
    """插入或更新追番记录，返回记录ID"""
    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT id FROM anime_tracking WHERE bangumi_id = ? AND season = ?",
        (anime.get("bangumi_id"), anime.get("season"))
    ).fetchone()

    if row:
        # 更新
        anime_id = row["id"]
        cursor.execute("""
            UPDATE anime_tracking SET
                series_id = ?, title_cn = ?, title_jp = ?,
                sub_group = ?, resolution = ?, total_episodes = ?,
                status = ?, updated_at = ?
            WHERE id = ?
        """, (
            anime.get("series_id"),
            anime.get("title_cn"),
            anime.get("title_jp"),
            anime.get("sub_group"),
            anime.get("resolution", "1080p"),
            anime.get("total_episodes"),
            anime.get("status", "ongoing"),
            now_iso(),
            anime_id,
        ))
    else:
        # 插入
        cursor.execute("""
            INSERT INTO anime_tracking
                (bangumi_id, series_id, title_cn, title_jp, season,
                 season_number, sub_group, resolution, total_episodes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            anime.get("bangumi_id"),
            anime.get("series_id"),
            anime.get("title_cn"),
            anime.get("title_jp"),
            anime.get("season"),
            anime.get("season_number", 1),
            anime.get("sub_group"),
            anime.get("resolution", "1080p"),
            anime.get("total_episodes"),
            anime.get("status", "ongoing"),
            now_iso(),
            now_iso(),
        ))
        anime_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return anime_id


def get_tracking_list(status: str = None) -> List[Dict]:
    """获取追番列表，可按状态过滤"""
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM anime_tracking WHERE status = ? ORDER BY title_cn",
            (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM anime_tracking ORDER BY status, title_cn"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracking_by_id(anime_id: int) -> Optional[Dict]:
    """根据ID获取追番记录"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM anime_tracking WHERE id = ?", (anime_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_tracking_by_bangumi(bangumi_id: int) -> Optional[Dict]:
    """根据 Bangumi ID 获取追番记录"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM anime_tracking WHERE bangumi_id = ?",
        (bangumi_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_tracking_status(anime_id: int, status: str):
    """更新追番状态"""
    conn = get_connection()
    conn.execute(
        "UPDATE anime_tracking SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), anime_id)
    )
    conn.commit()
    conn.close()


def get_downloaded_episodes(anime_id: int) -> List[int]:
    """获取某番已下载的集数列表"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT episode FROM download_history WHERE anime_id = ? AND status = 'completed'",
        (anime_id,)
    ).fetchall()
    conn.close()
    return [r["episode"] for r in rows]


# ============================================================
# download_history CRUD
# ============================================================

def is_episode_downloaded(anime_id: int, episode: int) -> bool:
    """检查某集是否已下载（防重复）"""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM download_history WHERE anime_id = ? AND episode = ? AND status = 'completed'",
        (anime_id, episode)
    ).fetchone()
    conn.close()
    return row is not None


def insert_download(record: Dict[str, Any]) -> int:
    """插入下载记录，防重复（anime_id + episode 唯一约束）"""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO download_history
                (anime_id, episode, sub_group, torrent_hash, torrent_title, file_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get("anime_id"),
            record.get("episode"),
            record.get("sub_group"),
            record.get("torrent_hash"),
            record.get("torrent_title"),
            record.get("file_path"),
            record.get("file_size"),
            record.get("status", "pending"),
        ))
        conn.commit()
        return cursor.lastrowid or 0
    except sqlite3.IntegrityError:
        logger.debug(f"重复下载记录: anime_id={record.get('anime_id')} ep={record.get('episode')}")
        return 0
    finally:
        conn.close()


def update_download_status(download_id: int = None, torrent_hash: str = None,
                           status: str = None, file_path: str = None,
                           scraped: bool = None):
    """更新下载记录状态"""
    conn = get_connection()
    fields = []
    values = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
        if status == "completed":
            fields.append("downloaded_at = ?")
            values.append(now_iso())

    if file_path is not None:
        fields.append("file_path = ?")
        values.append(file_path)

    if scraped is not None:
        fields.append("scraped = ?")
        values.append(1 if scraped else 0)
        if scraped:
            fields.append("scraped_at = ?")
            values.append(now_iso())

    if not fields:
        conn.close()
        return

    if download_id:
        query = f"UPDATE download_history SET {', '.join(fields)} WHERE id = ?"
        values.append(download_id)
    elif torrent_hash:
        query = f"UPDATE download_history SET {', '.join(fields)} WHERE torrent_hash = ?"
        values.append(torrent_hash)
    else:
        conn.close()
        return

    conn.execute(query, values)
    conn.commit()
    conn.close()


def get_pending_scrape() -> List[Dict]:
    """获取待刮削条目"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT dh.*, at.title_cn, at.title_jp
        FROM download_history dh
        JOIN anime_tracking at ON dh.anime_id = at.id
        WHERE dh.scraped = 0 AND dh.status = 'completed'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_seeding_cleanable() -> List[Dict]:
    """获取做种达标待清理条目"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM download_history
        WHERE seed_cleaned = 0
          AND status = 'completed'
          AND seeding_ratio >= 2.0
          AND seeding_hours >= 72
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_seeding_stats(torrent_hash: str, ratio: float, hours: float):
    """更新做种统计"""
    conn = get_connection()
    conn.execute("""
        UPDATE download_history
        SET seeding_ratio = ?, seeding_hours = ?
        WHERE torrent_hash = ?
    """, (ratio, hours, torrent_hash))
    conn.commit()
    conn.close()


def mark_seed_cleaned(download_id: int):
    """标记做种已清理"""
    conn = get_connection()
    conn.execute(
        "UPDATE download_history SET seed_cleaned = 1 WHERE id = ?",
        (download_id,)
    )
    conn.commit()
    conn.close()


def get_today_stats() -> Dict:
    """获取今日统计"""
    conn = get_connection()
    today = datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")

    total_downloaded = conn.execute("""
        SELECT COUNT(*) as c FROM download_history
        WHERE date(downloaded_at) = ?
    """, (today,)).fetchone()["c"]

    total_scraped = conn.execute("""
        SELECT COUNT(*) as c FROM download_history
        WHERE date(scraped_at) = ? AND scraped = 1
    """, (today,)).fetchone()["c"]

    seeding_count = conn.execute("""
        SELECT COUNT(*) as c FROM download_history
        WHERE status = 'completed' AND seed_cleaned = 0
    """).fetchone()["c"]

    conn.close()
    return {
        "date": today,
        "downloaded": total_downloaded,
        "scraped": total_scraped,
        "seeding": seeding_count,
    }


def get_recent_downloads(limit: int = 20) -> List[Dict]:
    """获取最近下载记录"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT dh.*, at.title_cn
        FROM download_history dh
        JOIN anime_tracking at ON dh.anime_id = at.id
        ORDER BY dh.downloaded_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# sub_group_fallback_log CRUD
# ============================================================

def log_sub_fallback(anime_id: int, episode: int,
                     preferred: str, actual: str) -> int:
    """记录字幕组降级"""
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO sub_group_fallback_log
            (anime_id, episode, preferred_group, actual_group, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (anime_id, episode, preferred, actual, now_iso()))
    conn.commit()
    log_id = cursor.lastrowid
    conn.close()
    logger.info(f"字幕组降级: anime_id={anime_id} ep={episode} {preferred}→{actual}")
    return log_id


def get_unnotified_fallbacks() -> List[Dict]:
    """获取未通知的字幕组降级记录"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fl.*, at.title_cn
        FROM sub_group_fallback_log fl
        JOIN anime_tracking at ON fl.anime_id = at.id
        WHERE fl.notified = 0
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_fallback_notified(log_ids: List[int]):
    """标记字幕组降级已通知"""
    if not log_ids:
        return
    conn = get_connection()
    placeholders = ",".join("?" * len(log_ids))
    conn.execute(
        f"UPDATE sub_group_fallback_log SET notified = 1 WHERE id IN ({placeholders})",
        log_ids
    )
    conn.commit()
    conn.close()
