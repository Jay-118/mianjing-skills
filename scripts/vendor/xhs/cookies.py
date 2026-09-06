"""Cookie 文件持久化，支持 CDP cookie 注入/导出。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def get_cookies_file_path(account: str = "") -> str:
    """获取 cookies 文件路径。

    优先级：
    1. 多账号模式：~/.xhs/accounts/{account}/cookies.json
    2. COOKIES_PATH 环境变量
    3. /tmp 旧路径（向后兼容，仅当文件已存在时）
    4. ~/.xhs/cookies.json（稳定默认路径）
    """
    if account:
        account_dir = Path.home() / ".xhs" / "accounts" / account
        account_dir.mkdir(parents=True, exist_ok=True)
        return str(account_dir / "cookies.json")

    # 环境变量
    env_path = os.getenv("COOKIES_PATH")
    if env_path:
        return env_path

    # 旧路径（向后兼容）
    import tempfile

    old_path = os.path.join(tempfile.gettempdir(), "cookies.json")
    if os.path.exists(old_path):
        return old_path

    # 稳定默认路径
    default_dir = Path.home() / ".xhs"
    default_dir.mkdir(parents=True, exist_ok=True)
    return str(default_dir / "cookies.json")


def load_cookies(path: str) -> bytes | None:
    """从文件加载 cookies。"""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def save_cookies(path: str, data: bytes) -> None:
    """保存 cookies 到文件。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def delete_cookies(path: str) -> None:
    """删除 cookies 文件。"""
    import contextlib

    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


def export_cookies_from_browser(page) -> list[dict]:
    """从浏览器通过 CDP 导出所有小红书相关 cookies。

    Args:
        page: CDP Page 对象。

    Returns:
        Cookie 字典列表（CDP 格式）。
    """
    try:
        result = page._send_session(
            "Network.getCookies",
            {"urls": [
                "https://www.xiaohongshu.com",
                "https://creator.xiaohongshu.com",
                "https://edith.xiaohongshu.com",
            ]},
        )
        cookies = result.get("cookies", [])
        logger.info("从浏览器导出 %d 个 cookies", len(cookies))
        return cookies
    except Exception as e:
        logger.warning("导出 cookies 失败: %s", e)
        return []


def inject_cookies_to_browser(page, cookies: list[dict]) -> bool:
    """将 cookies 注入到浏览器（通过 CDP Network.setCookies）。

    Args:
        page: CDP Page 对象。
        cookies: Cookie 字典列表（CDP 格式）。

    Returns:
        True 注入成功，False 失败。
    """
    if not cookies:
        return False
    try:
        # 清理 cookie 数据中可能导致 CDP 报错的字段
        clean_cookies = []
        for c in cookies:
            clean = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".xiaohongshu.com"),
                "path": c.get("path", "/"),
            }
            # 可选字段
            if c.get("secure"):
                clean["secure"] = True
            if c.get("httpOnly"):
                clean["httpOnly"] = True
            if c.get("sameSite"):
                clean["sameSite"] = c["sameSite"]
            if c.get("expires") and c["expires"] > 0:
                clean["expires"] = c["expires"]
            clean_cookies.append(clean)

        page._send_session("Network.enable")
        page._send_session("Network.setCookies", {"cookies": clean_cookies})
        logger.info("注入 %d 个 cookies 到浏览器", len(clean_cookies))
        return True
    except Exception as e:
        logger.warning("注入 cookies 失败: %s", e)
        return False


def save_cookies_to_file(cookies: list[dict], path: str) -> None:
    """将 CDP 格式的 cookies 保存到 JSON 文件。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info("Cookies 已保存到: %s", path)


def load_cookies_from_file(path: str) -> list[dict] | None:
    """从 JSON 文件加载 CDP 格式的 cookies。

    Returns:
        Cookie 字典列表，文件不存在或格式错误返回 None。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
            logger.info("从文件加载 %d 个 cookies: %s", len(data), path)
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return None
