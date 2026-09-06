"""人类行为模拟参数（延迟、滚动、悬停），对应 Go feed_detail.go 中的常量。

反检测延迟参数（固定值，直接修改此处即可调优）：
  XHS_BASE_SLEEP         每次请求后的基础等待秒数
  XHS_JITTER_MIN/MAX     基础等待叠加的随机抖动范围（秒）
  XHS_PAGE_SLEEP_MIN/MAX 翻页后等待范围（秒）
  XHS_LONG_REST_MIN/MAX  发布后长休眠范围（秒）
  XHS_HUMAN_SIM          是否启用人类操作模拟（随机滑动/点击等）

调优建议：
  想要更稳：提高 XHS_BASE_SLEEP、XHS_PAGE_SLEEP_*、XHS_LONG_REST_*
  想要更快：降低上述值
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)

# ========== 反检测延迟参数（固定值，直接改这里调优） ==========

# 每次请求后基础等待秒数
XHS_BASE_SLEEP: float = 3.0
# 基础等待上叠加的随机抖动范围（秒）
XHS_JITTER_MIN: float = 1.0
XHS_JITTER_MAX: float = 5.0
# 翻页搜索结果后的等待范围（秒）
XHS_PAGE_SLEEP_MIN: float = 5.0
XHS_PAGE_SLEEP_MAX: float = 12.0
# 发布后长休眠范围（秒）
XHS_LONG_REST_MIN: float = 60.0
XHS_LONG_REST_MAX: float = 180.0
# 是否启用人类操作模拟（随机滑动、点击空白等）
XHS_HUMAN_SIM: bool = True


# ========== 配置常量 ==========
DEFAULT_MAX_ATTEMPTS = 500
STAGNANT_LIMIT = 20
MIN_SCROLL_DELTA = 10
MAX_CLICK_PER_ROUND = 3
STAGNANT_CHECK_THRESHOLD = 2
LARGE_SCROLL_TRIGGER = 5
BUTTON_CLICK_INTERVAL = 3
FINAL_SPRINT_PUSH_COUNT = 15

# ========== 延迟范围（毫秒） ==========
# 适度拉长阅读/导航类延迟，弱化"机器节奏"特征。
HUMAN_DELAY = (300, 800)
REACTION_TIME = (300, 900)
HOVER_TIME = (150, 400)
READ_TIME = (800, 2500)
SHORT_READ = (700, 2000)
SCROLL_WAIT = (120, 260)
POST_SCROLL = (350, 650)


# ========== 核心延迟函数 ==========


def sleep_random(min_ms: int, max_ms: int) -> None:
    """随机延迟。"""
    if max_ms <= min_ms:
        time.sleep(min_ms / 1000.0)
        return
    delay = random.randint(min_ms, max_ms) / 1000.0
    time.sleep(delay)


def sleep_with_jitter() -> None:
    """基础等待 + 随机抖动，用于每次关键请求后。

    总等待 = XHS_BASE_SLEEP + uniform(XHS_JITTER_MIN, XHS_JITTER_MAX)
    """
    base = XHS_BASE_SLEEP
    jitter = random.uniform(XHS_JITTER_MIN, XHS_JITTER_MAX)
    total = base + jitter
    logger.debug("sleep_with_jitter: base=%.1fs + jitter=%.1fs = %.1fs", base, jitter, total)
    time.sleep(total)


def page_turn_sleep() -> None:
    """翻页后等待，模拟用户翻页后停留浏览。"""
    delay = random.uniform(XHS_PAGE_SLEEP_MIN, XHS_PAGE_SLEEP_MAX)
    logger.debug("page_turn_sleep: %.1fs", delay)
    time.sleep(delay)


def post_publish_rest() -> None:
    """发布完成后的长休眠，降低连续发布的机器特征。"""
    delay = random.uniform(XHS_LONG_REST_MIN, XHS_LONG_REST_MAX)
    logger.info("发布后长休眠: %.0f 秒", delay)
    time.sleep(delay)


def navigation_delay() -> None:
    """页面导航后的随机等待，模拟人类阅读。"""
    sleep_random(1500, 3000)
    # 额外叠加抖动
    jitter = random.uniform(XHS_JITTER_MIN / 2, XHS_JITTER_MAX / 2)
    time.sleep(jitter)


# ========== 人类行为模拟 ==========


def simulate_human_behavior(page) -> None:
    """在页面上模拟人类浏览行为：随机滑动、悬停、偶尔点击空白区域。

    仅在 XHS_HUMAN_SIM=1 时执行。传入 cdp.Page 对象。
    """
    if not XHS_HUMAN_SIM:
        return

    try:
        viewport_w = page.evaluate("window.innerWidth") or 1200
        viewport_h = page.evaluate("window.innerHeight") or 800
    except Exception:
        viewport_w, viewport_h = 1200, 800

    actions = random.randint(2, 5)
    logger.debug("simulate_human_behavior: %d actions", actions)

    for _ in range(actions):
        action = random.choices(
            ["scroll", "mouse_move", "click_blank", "hover_pause"],
            weights=[40, 30, 10, 20],
            k=1,
        )[0]

        try:
            if action == "scroll":
                # 随机方向滚动
                direction = random.choice([-1, 1])
                delta = random.randint(100, 400) * direction
                page.scroll_by(0, delta)
                sleep_random(300, 800)

            elif action == "mouse_move":
                # 随机移动鼠标到页面某个位置
                x = random.uniform(50, viewport_w - 50)
                y = random.uniform(50, viewport_h - 50)
                page.mouse_move(x, y)
                sleep_random(200, 600)

            elif action == "click_blank":
                # 点击页面空白区域（避开交互元素的安全区域）
                x = random.uniform(viewport_w * 0.7, viewport_w * 0.95)
                y = random.uniform(10, 60)
                page.mouse_click(float(x), float(y))
                sleep_random(300, 700)

            elif action == "hover_pause":
                # 悬停在随机位置短暂停留
                x = random.uniform(100, viewport_w - 100)
                y = random.uniform(100, viewport_h - 100)
                page.mouse_move(x, y)
                sleep_random(500, 1500)
        except Exception:
            pass

    # 最终等一小段
    sleep_random(200, 500)


def simulate_reading(page, min_sec: float = 2.0, max_sec: float = 6.0) -> None:
    """模拟用户阅读页面内容：缓慢向下滑动 + 停顿。"""
    if not XHS_HUMAN_SIM:
        sleep_random(int(min_sec * 1000), int(max_sec * 1000))
        return

    read_time = random.uniform(min_sec, max_sec)
    end_time = time.monotonic() + read_time

    try:
        while time.monotonic() < end_time:
            delta = random.randint(30, 120)
            page.scroll_by(0, delta)
            sleep_random(400, 1200)
    except Exception:
        time.sleep(max(0, end_time - time.monotonic()))


# ========== 滚动参数 ==========


def get_scroll_interval(speed: str) -> float:
    """根据速度获取滚动间隔（秒）。"""
    if speed == "slow":
        return (1200 + random.randint(0, 300)) / 1000.0
    if speed == "fast":
        return (300 + random.randint(0, 100)) / 1000.0
    # normal
    return (600 + random.randint(0, 200)) / 1000.0


def get_scroll_ratio(speed: str) -> float:
    """根据速度获取滚动比例。"""
    if speed == "slow":
        return 0.5
    if speed == "fast":
        return 0.9
    return 0.7


def calculate_scroll_delta(viewport_height: int, base_ratio: float) -> float:
    """计算滚动距离。"""
    scroll_delta = viewport_height * (base_ratio + random.random() * 0.2)
    if scroll_delta < 400:
        scroll_delta = 400.0
    return scroll_delta + random.randint(-50, 50)


# 页面不可访问关键词
INACCESSIBLE_KEYWORDS = [
    "当前笔记暂时无法浏览",
    "该内容因违规已被删除",
    "该笔记已被删除",
    "内容不存在",
    "笔记不存在",
    "已失效",
    "私密笔记",
    "仅作者可见",
    "因用户设置，你无法查看",
    "因违规无法查看",
]
