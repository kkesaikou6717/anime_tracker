"""
Server酱 通知推送模块
- 下载完成通知
- 刮削完成通知
- 做种达标通知
- 异常通知
- 日报推送

Server酱 API: https://sctapi.ftqq.com/{sendkey}.send
"""

import logging
from typing import Optional, Dict

import httpx

import config

logger = logging.getLogger(__name__)

# Server酱 API 地址
SERVER_CHAN_API = "https://sctapi.ftqq.com"


class Notifier:
    """Server酱 通知服务"""

    def __init__(self):
        self.sendkey = config.get_sendkey()
        if not self.sendkey:
            logger.warning("Server酱 SendKey 未配置！通知功能不可用")

        self.client = httpx.Client(timeout=15.0)

    def close(self):
        self.client.close()

    @property
    def enabled(self) -> bool:
        return bool(self.sendkey)

    def _send(self, title: str, content: str = "") -> bool:
        """发送 Server酱 通知"""
        if not self.enabled:
            logger.warning(f"通知未启用，跳过: {title}")
            return False

        url = f"{SERVER_CHAN_API}/{self.sendkey}.send"

        try:
            resp = self.client.post(url, data={
                "title": title,
                "desp": content,
            })
            data = resp.json()
            if data.get("code") == 0:
                logger.info(f"通知发送成功: {title}")
                return True
            else:
                logger.error(f"通知发送失败: {data.get('message', resp.text)}")
                return False
        except Exception as e:
            logger.error(f"通知发送异常: {e}")
            return False

    # ================================================================
    # 各类通知
    # ================================================================

    def notify_new_episode(self, title_cn: str, episode: int,
                           sub_group: str, resolution: str = "1080p") -> bool:
        """新集上线通知"""
        return self._send(
            title="🎬 新集上线",
            content=f"{title_cn} 第{episode}集 已匹配 [{sub_group}] {resolution}\n"
                    f"正在导入下载..."
        )

    def notify_download_complete(self, title_cn: str, episode: int) -> bool:
        """下载完成通知"""
        return self._send(
            title="✅ 下载完成",
            content=f"{title_cn} 第{episode}集 下载完成\n正在复制到 Anime 目录并触发刮削..."
        )

    def notify_scrape_complete(self, title_cn: str, episode: int,
                               dest_path: str = "") -> bool:
        """刮削完成通知"""
        content = f"{title_cn} 第{episode}集 刮削完成"
        if dest_path:
            content += f"\n→ {dest_path}"
        return self._send(title="✅ 刮削完成", content=content)

    def notify_seed_cleanup(self, title_cn: str, episode: int,
                            ratio: float) -> bool:
        """做种达标清理通知"""
        return self._send(
            title="🗑️ 做种达标",
            content=f"{title_cn} 第{episode}集 做种已达标(比率 {ratio:.1f})\n"
                    f"已清理 Temp 临时文件 + 删除 qB 任务"
        )

    def notify_archive_complete(self, season: str, finished_count: int,
                                continuing_count: int) -> bool:
        """季度归档完成通知"""
        return self._send(
            title="📦 季度归档",
            content=f"{season} 番剧已归档：{finished_count}部完结"
                    + (f"，{continuing_count}部多季续播" if continuing_count else "")
        )

    def notify_sub_fallback(self, title_cn: str, episode: int,
                            preferred: str, actual: str) -> bool:
        """字幕组降级通知"""
        return self._send(
            title="⚠️ 字幕组降级",
            content=f"{title_cn} 第{episode}集\n"
                    f"首选: {preferred}\n"
                    f"实际: {actual}\n"
                    f"首选字幕组未更新"
        )

    def notify_error(self, title: str, error_msg: str) -> bool:
        """异常通知"""
        return self._send(
            title=f"⚠️ 异常提醒: {title}",
            content=error_msg
        )

    def send_daily_report(self, report: Dict) -> bool:
        """发送日报"""
        stats = report.get("stats", {})
        tracking = report.get("tracking", [])
        recent = report.get("recent_downloads", [])

        # 构建日报内容
        lines = [
            "━━━━━━━━━━━━━━━━━━━",
            f"🎸 Anime Tracker 日报 | {stats.get('date', '')}",
            "━━━━━━━━━━━━━━━━━━━",
            "",
            "📥 今日下载",
        ]

        if recent:
            for d in recent[:10]:
                status_icon = "✅" if d.get("scraped") else "⏳"
                lines.append(f"  {status_icon} {d.get('title_cn', '')} EP{d.get('episode', '')}")
        else:
            lines.append("  今日无新下载")

        lines.append("")
        lines.append(f"📊 统计")
        lines.append(f"  • 今日下载: {stats.get('downloaded', 0)} 集")
        lines.append(f"  • 今日刮削: {stats.get('scraped', 0)} 集")
        lines.append(f"  • 做种中: {stats.get('seeding', 0)} 个任务")

        lines.append("")
        lines.append(f"📋 追番列表: {stats.get('tracking_count', 0)} 部进行中")
        for t in tracking[:5]:
            lines.append(f"  • {t.get('title_cn', '')} (EP1-{t.get('total_episodes', '?')})")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━")

        content = "\n".join(lines)
        return self._send(
            title=f"Anime Tracker 日报 {stats.get('date', '')}",
            content=content,
        )


# 全局单例
_notifier: Optional[Notifier] = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
