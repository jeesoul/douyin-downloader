import logging
import threading
import time

from playwright.sync_api import Error, sync_playwright

from ...domain.models import Content, DownloadError, ResolvedLink, StatusCallback
from ...infrastructure.runtime import check_cancel, ensure_browser
from .content import decode_page_data, find_aweme, parse_content
from .links import USER_AGENT

LOGGER = logging.getLogger(__name__)


def capture_content(
    link: ResolvedLink,
    show_browser: bool = False,
    cancel: threading.Event | None = None,
    on_status: StatusCallback = lambda _: None,
) -> tuple[Content, list[dict]]:
    """匹配目标作品的数据，优先无头获取，必要时显示浏览器供用户验证。"""
    ensure_browser(cancel, on_status)
    with sync_playwright() as p:
        for visible in [True] if show_browser else [False, True]:
            check_cancel(cancel)
            on_status(
                "Waiting for browser verification..." if visible else "Getting post information..."
            )
            browser = p.chromium.launch(
                headless=not visible,
                channel="chromium",
                args=["--disable-blink-features=AutomationControlled", "--mute-audio"],
            )
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT, locale="zh-CN", viewport={"width": 1512, "height": 950}
                )
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
                )
                page = context.new_page()
                responses = []

                def on_response(response):
                    if "/aweme/" in response.url and "json" in response.headers.get(
                        "content-type", ""
                    ):
                        try:
                            value = find_aweme(response.json(), link.aweme_id)
                            if value:
                                responses.append(value)
                        except (ValueError, Error):
                            pass

                page.on("response", on_response)
                try:
                    page.goto(link.page_url, wait_until="domcontentloaded", timeout=30000)
                except Error:
                    LOGGER.info("Page navigation did not complete; waiting for post data.")
                deadline = time.monotonic() + (60 if visible else 20)
                while time.monotonic() < deadline:
                    check_cancel(cancel)
                    aweme = responses[0] if responses else None
                    if not aweme:
                        data = page.evaluate(
                            "() => ({render:document.getElementById('RENDER_DATA')?.textContent || null, flight:window.__pace_f || [], ssr:window.SSR_RENDER_DATA || null})"
                        )
                        for item in [
                            data.get("ssr"),
                            *decode_page_data(data.get("render"), data.get("flight")),
                        ]:
                            aweme = find_aweme(item, link.aweme_id)
                            if aweme:
                                break
                    if aweme:
                        content = parse_content(aweme, link.aweme_id)
                        if content.images or content.qualities:
                            return content, context.cookies()
                    page.wait_for_timeout(500)
            finally:
                browser.close()
    raise DownloadError(
        "No downloadable post data received. The post may require login/verification, be private, deleted, or unavailable."
    )
