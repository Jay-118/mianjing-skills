"""小红书自动化异常体系。"""


class XHSError(Exception):
    """小红书自动化基础异常。"""


class RetryableError(XHSError):
    """可重试的异常基类。调用方可根据此类型决定是否重试。"""


class NoFeedsError(XHSError):
    """没有捕获到 feeds 数据。"""

    def __init__(self) -> None:
        super().__init__("没有捕获到 feeds 数据")


class NoFeedDetailError(XHSError):
    """没有捕获到 feed 详情数据。"""

    def __init__(self) -> None:
        super().__init__("没有捕获到 feed 详情数据")


class NotLoggedInError(XHSError):
    """未登录。"""

    def __init__(self) -> None:
        super().__init__("未登录，请先扫码登录")


class PageNotAccessibleError(XHSError):
    """页面不可访问。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"笔记不可访问: {reason}")


class UploadTimeoutError(RetryableError):
    """上传超时（可重试）。"""


class PublishError(XHSError):
    """发布失败。"""


class TitleTooLongError(PublishError):
    """标题超过长度限制。"""

    def __init__(self, current: str, maximum: str) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(f"当前输入长度为{current}，最大长度为{maximum}")


class ContentTooLongError(PublishError):
    """正文超过长度限制。"""

    def __init__(self, current: str, maximum: str) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(f"当前输入长度为{current}，最大长度为{maximum}")


class RateLimitError(RetryableError):
    """请求频率过高，验证码获取失败（可重试）。"""

    def __init__(self) -> None:
        super().__init__("请求太频繁，验证码获取失败，请重启浏览器后重试")


class CDPError(RetryableError):
    """CDP 通信异常（可重试）。"""


class ElementNotFoundError(XHSError):
    """页面元素未找到。"""

    def __init__(self, selector: str) -> None:
        self.selector = selector
        super().__init__(f"未找到元素: {selector}")


class CookieExpiredError(XHSError):
    """Cookie 已过期。"""

    def __init__(self) -> None:
        super().__init__("Cookie 已过期或无效，需重新登录")


class FollowError(XHSError):
    """关注操作失败。"""

    def __init__(self, user_id: str, reason: str = "") -> None:
        self.user_id = user_id
        msg = f"关注用户 {user_id} 失败"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
