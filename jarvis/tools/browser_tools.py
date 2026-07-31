"""
Browser Tools - Computer Use, 100% free local via Playwright
JARVIS controls browser like Claude Computer Use but free and local

Capabilities: navigate, click, type, get content, screenshot, search, JS exec
"""

from ..config import config

# Lazy singleton
_browser = None

def _get_browser():
    global _browser
    if _browser is None:
        try:
            from ..computer import BrowserController
            _browser = BrowserController(headless=True)
        except Exception as e:
            print(f"BrowserController not available: {e}")
    return _browser


def browser_start(headless: bool = True) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available. Install: pip install playwright && playwright install chromium (free)"
        return browser.start()
    except Exception as e:
        return f"Browser start failed: {e}"


def browser_navigate(url: str) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.navigate(url)
    except Exception as e:
        return f"Navigate failed: {e}"


def browser_get_content(selector: str = None) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.get_content(selector=selector)
    except Exception as e:
        return f"Get content failed: {e}"


def browser_click(selector: str) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.click(selector)
    except Exception as e:
        return f"Click failed: {e}"


def browser_type(selector: str, text: str, press_enter: bool = False) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.type_text(selector, text, press_enter=press_enter)
    except Exception as e:
        return f"Type failed: {e}"


def browser_screenshot(path: str = None) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.screenshot(path=path)
    except Exception as e:
        return f"Screenshot failed: {e}"


def browser_search(query: str, engine: str = "duckduckgo") -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.search(query, engine=engine)
    except Exception as e:
        return f"Browser search failed: {e}"


def browser_execute_js(js_code: str) -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.execute_js(js_code)
    except Exception as e:
        return f"JS exec failed: {e}"


def browser_get_url() -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.get_url()
    except Exception as e:
        return f"Get URL failed: {e}"


def browser_stop() -> str:
    try:
        browser = _get_browser()
        if not browser:
            return "Browser not available"
        return browser.stop()
    except Exception as e:
        return f"Browser stop failed: {e}"
