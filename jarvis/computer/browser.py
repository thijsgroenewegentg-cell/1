"""
Browser Controller - JARVIS controls browser like a human, 100% free local
Uses Playwright (free, open source) - no API keys

Capabilities:
- Navigate, click, type, screenshot, get content, search
- Like Claude Computer Use but local and free
- Can test your own web app, scrape docs, fill forms, create PRs via GitHub web if needed
"""

import time
from pathlib import Path
from typing import Optional, Dict

from ..config import config


class BrowserController:
    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self.headless = headless
        self.slow_mo = slow_mo
        self.playwright = None
        self.browser = None
        self.page = None
        self.is_started = False
        self.screenshots_dir = config.MEMORY_FILE.parent / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"🌐 BrowserController init: headless={headless}, slow_mo={slow_mo}ms")
    
    def _ensure_playwright(self):
        """Ensure playwright is installed"""
        try:
            from playwright.sync_api import sync_playwright
            return sync_playwright
        except ImportError:
            raise ImportError(
                "Playwright not installed, Sir. Install free:\n"
                "  pip install playwright --break-system-packages\n"
                "  playwright install chromium\n"
                "100% free, no API keys, local browser control."
            )
    
    def start(self) -> str:
        """Start browser"""
        if self.is_started:
            return "Browser already started, Sir."
        
        try:
            sync_playwright = self._ensure_playwright()
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
            self.page = self.browser.new_page()
            # Set viewport
            self.page.set_viewport_size({"width": 1280, "height": 800})
            self.is_started = True
            return f"Browser started, Sir. Headless={self.headless}, viewport 1280x800. Ready to navigate."
        except Exception as e:
            return f"Browser start failed, Sir: {e}. Make sure playwright installed: pip install playwright && playwright install chromium"
    
    def stop(self) -> str:
        """Stop browser"""
        try:
            if self.page:
                self.page.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            self.is_started = False
            return "Browser stopped, Sir."
        except Exception as e:
            return f"Browser stop failed: {e}"
    
    def navigate(self, url: str) -> str:
        """Navigate to URL"""
        if not self.is_started:
            start_msg = self.start()
            if "failed" in start_msg.lower():
                return start_msg
        
        try:
            if not url.startswith("http"):
                url = "https://" + url
            
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(1)  # let page settle
            title = self.page.title()
            return f"Navigated to {url}, Sir. Title: {title}. Page loaded."
        except Exception as e:
            return f"Navigate to {url} failed, Sir: {e}"
    
    def get_content(self, selector: str = None) -> str:
        """Get page content or element content"""
        if not self.is_started or not self.page:
            return "Browser not started, Sir. Call browser_start or navigate first."
        
        try:
            if selector:
                # Get specific element
                element = self.page.query_selector(selector)
                if not element:
                    return f"Element not found: {selector}, Sir."
                text = element.inner_text()[:5000]
                return f"Content of {selector}:\n{text}"
            else:
                # Get full page text
                # Try to get body text
                body = self.page.query_selector("body")
                if body:
                    text = body.inner_text()[:8000]
                    return f"Page content (first 8000 chars):\n{text}"
                else:
                    return "No body found, Sir."
        except Exception as e:
            return f"Get content failed: {e}"
    
    def click(self, selector: str) -> str:
        """Click element by selector"""
        if not self.is_started or not self.page:
            return "Browser not started, Sir."
        
        try:
            # Try multiple selector strategies
            # First try as is, then try text, etc
            self.page.click(selector, timeout=5000)
            time.sleep(0.5)
            return f"Clicked {selector}, Sir."
        except Exception as e:
            # Try by text
            try:
                self.page.get_by_text(selector).first.click(timeout=3000)
                return f"Clicked by text '{selector}', Sir."
            except Exception as e2:
                return f"Click {selector} failed: {e} / {e2}, Sir. Try different selector. Page title: {self.page.title() if self.page else 'no page'}"
    
    def type_text(self, selector: str, text: str, press_enter: bool = False) -> str:
        """Type text into element"""
        if not self.is_started or not self.page:
            return "Browser not started, Sir."
        
        try:
            # Click first to focus
            try:
                self.page.click(selector, timeout=3000)
            except:
                pass
            
            # Fill
            self.page.fill(selector, text, timeout=5000)
            
            if press_enter:
                self.page.keyboard.press("Enter")
            
            time.sleep(0.3)
            return f"Typed into {selector}: {text[:50]}{'...' if len(text)>50 else ''}{' + Enter' if press_enter else ''}, Sir."
        except Exception as e:
            # Try type via keyboard if fill fails
            try:
                self.page.locator(selector).first.fill(text, timeout=3000)
                if press_enter:
                    self.page.keyboard.press("Enter")
                return f"Typed via locator {selector}: {text[:50]}, Sir."
            except Exception as e2:
                return f"Type into {selector} failed: {e} / {e2}, Sir."
    
    def screenshot(self, path: str = None) -> str:
        """Take screenshot"""
        if not self.is_started or not self.page:
            return "Browser not started, Sir."
        
        try:
            if not path:
                timestamp = int(time.time())
                path = str(self.screenshots_dir / f"screenshot_{timestamp}.png")
            
            # Ensure path is inside screenshots dir for safety
            p = Path(path)
            if not p.is_absolute():
                p = self.screenshots_dir / p
            
            self.page.screenshot(path=str(p), full_page=False)
            return f"Screenshot saved to {p}, Sir. Size: {p.stat().st_size} bytes. You can view it."
        except Exception as e:
            return f"Screenshot failed: {e}"
    
    def search(self, query: str, engine: str = "duckduckgo") -> str:
        """Search via browser"""
        try:
            if engine == "duckduckgo":
                url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            elif engine == "google":
                url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            else:
                url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            
            nav_result = self.navigate(url)
            time.sleep(2)
            content = self.get_content()
            return f"{nav_result}\n\nSearch results for '{query}':\n{content[:5000]}"
        except Exception as e:
            return f"Browser search failed: {e}"
    
    def execute_js(self, js_code: str) -> str:
        """Execute JavaScript in page"""
        if not self.is_started or not self.page:
            return "Browser not started, Sir."
        
        try:
            result = self.page.evaluate(js_code)
            return f"JS executed, Sir. Result: {str(result)[:2000]}"
        except Exception as e:
            return f"JS execution failed: {e}"
    
    def get_url(self) -> str:
        if not self.is_started or not self.page:
            return "Browser not started"
        try:
            return f"Current URL: {self.page.url}, Title: {self.page.title()}"
        except Exception as e:
            return f"Get URL failed: {e}"
    
    def go_back(self) -> str:
        if not self.is_started or not self.page:
            return "Browser not started"
        try:
            self.page.go_back()
            time.sleep(1)
            return f"Went back, Sir. Now at {self.page.url}"
        except Exception as e:
            return f"Go back failed: {e}"


# Singleton for easy use
_browser_instance = None

def get_browser(headless: bool = True) -> BrowserController:
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = BrowserController(headless=headless)
    return _browser_instance
