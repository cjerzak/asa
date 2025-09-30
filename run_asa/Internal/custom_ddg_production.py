# custom_duckduckgo.py
#
# LangChain‑compatible DuckDuckGo search wrapper with:
#   • optional real Chrome/Chromium via Selenium
#   • proxy + arbitrary headers on every tier
#   • automatic proxy‑bypass for Chromedriver handshake
#   • smart retries and a final pure‑Requests HTML fallback
#
import contextlib
import logging
import os
import traceback
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup
from ddgs import ddgs  # ddgs.DDGS is a class, ddgs.ddgs is a module
from ddgs import DDGS  # ddgs.DDGS is a class, ddgs.ddgs is a module
from ddgs.exceptions import DDGSException
from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun
from langchain_community.utilities.duckduckgo_search import DuckDuckGoSearchAPIWrapper
from pydantic import Field
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import requests
import random as random
import primp

INTERNAL_MAX_RETURN = 10
logger = logging.getLogger(__name__)
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

__all__ = [
    "PatchedDuckDuckGoSearchAPIWrapper",
    "PatchedDuckDuckGoSearchRun",
    "BrowserDuckDuckGoSearchAPIWrapper",
    "BrowserDuckDuckGoSearchRun",
]

# ────────────────────────────────────────────────────────────────────────
# Helper tier 2 – ddgs HTTP API (with retry and polite UA)
# ────────────────────────────────────────────────────────────────────────
def _with_ddgs(
    proxy: str | None,
    headers: Dict[str, str] | None,
    fn: Callable[[ddgs], Any],
    *,
    retries: int = 3,
    backoff: float = 1.5,
) -> Any:
    proxy = proxy or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    headers = dict(headers or {})
    headers.setdefault("User-Agent", _DEFAULT_UA)

    if proxy:
        os.environ.setdefault("HTTP_PROXY", proxy)
        os.environ.setdefault("HTTPS_PROXY", proxy)

    sleep = 0.01
    for attempt in range(1, retries + 1):
        try:
            #with DDGS(proxy=proxy, headers=headers, timeout=20) as client:
            with ddgs(proxy=proxy, timeout=20) as client:
                return fn(client)
        except DDGSException as exc:
            logger.warning("ddgs raised %s (try %d/%d)", exc, attempt, retries)
            if attempt == retries:
                raise
            time.sleep(sleep)
            sleep *= backoff


# ────────────────────────────────────────────────────────────────────────
# Helper tier 1 – real browser (Selenium)
# ────────────────────────────────────────────────────────────────────────
def _new_driver(
    *,
    proxy: str | None,
    headers: Dict[str, str] | None,
    headless: bool,
    bypass_proxy_for_driver: bool,
 ) -> webdriver.Firefox:
# ) -> webdriver.Chrome: # if using chrome

    opts = Options()
    opts.add_argument("--headless") # for Firefox 
    #opts.add_argument("--headless=new") # for Chrome 
    #opts.add_argument('--window-size=1600,900')

    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    #opts.add_argument('--disable-search-engine-choice-screen')

    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")

    # Temporarily clear proxies so Selenium‑Manager can download Chromedriver
    saved_env: Dict[str, str] = {}
    if bypass_proxy_for_driver:
        for var in ("HTTP_PROXY", "HTTPS_PROXY"):
            if var in os.environ:
                saved_env[var] = os.environ.pop(var)

    try:
        driver = webdriver.Chrome(options=opts)
    finally:
        os.environ.update(saved_env)

    if headers:
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": headers})
        except Exception as e:  # pragma: no cover
            logger.debug("CDP header injection failed: %s", e)

    return driver


def _browser_search(
    query: str,
    *,
    max_results: int = 10,
    proxy: str | None,
    headers: Dict[str, str] | None,
    headless: bool,
    bypass_proxy_for_driver: bool,
    timeout: int = 15,
) -> List[Dict[str, str]]:
    
    print("In _browser_search")
    max_results = int(  INTERNAL_MAX_RETURN ) # hardcode 
    
    driver = _new_driver(
        proxy=proxy,
        headers=headers,
        headless=headless,
        bypass_proxy_for_driver=bypass_proxy_for_driver,
    )
    try:
        driver.get(f"https://duckduckgo.com/html/?q={quote(query)}")
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.result__a"))
        )
        soup = BeautifulSoup(driver.page_source, "html.parser")

        #print(soup)
        #print("Selected:")
        #print(soup.select("a.result__snippet"))
        result_links = soup.select("a.result__a")[:max_results]
        result_snippets = soup.select("a.result__snippet")[:max_results]
        
        # return block
        from urllib.parse import urlparse, parse_qs, unquote
        return_content = []
        for idx, link in enumerate(result_links):
            raw_href = link["href"]
            # extract & decode uddg (or fall back to the raw href)
            real_url = unquote(
                parse_qs(urlparse(raw_href).query)
                .get("uddg", [raw_href])[0]
                )
            snippet = (
                result_snippets[idx].get_text(strip=True)
                if idx < len(result_snippets)
                else ""
                )
            return_content.append({
            "id": idx + 1,
            "title": link.get_text(strip=True),
            "href": raw_href,
                "body": f"__START_OF_SOURCE {idx + 1}__ <CONTENT> {snippet} </CONTENT> <URL> {real_url} </URL> __END_OF_SOURCE  {idx + 1}__"
            })

        #print("Returning:")
        #print(return_content)
    
        return return_content
    finally:
        time.sleep(random.uniform(0, 0.01))
        with contextlib.suppress(Exception):
            driver.quit()


# ────────────────────────────────────────────────────────────────────────
# Helper tier 3 – tiny Requests + BeautifulSoup fallback
# ────────────────────────────────────────────────────────────────────────
def _requests_scrape(
    query: str,
    *,
    max_results: int,
    proxy: str | None,
    headers: Dict[str, str] | None,
    timeout: int = 10,
) -> List[Dict[str, str]]:
    """
    Very small “Plan C” that fetches the DuckDuckGo Lite HTML endpoint
    and scrapes results.  No Javascript, so it’s low‑rate and robust.
    """
    url = "https://html.duckduckgo.com/html"
    headers = dict(headers or {})
    headers.setdefault("User-Agent", _DEFAULT_UA)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    resp = requests.post(
        url,
        data=urlencode({"q": query}),
        headers=headers,
        proxies=proxies,
        timeout=timeout,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results: List[Dict[str, str]] = []
    for i, a in enumerate(soup.select("a.result__a")[:max_results], 1):
        results.append({"id": i, "title": a.get_text(strip=True), "href": a["href"], "body": ""})
    return results


# ────────────────────────────────────────────────────────────────────────
# Public LangChain‑compatible wrappers
# ────────────────────────────────────────────────────────────────────────
class PatchedDuckDuckGoSearchAPIWrapper(DuckDuckGoSearchAPIWrapper):
    """
    A robust DuckDuckGo wrapper with three search tiers.
    """

    # Upstream fields
    k: int = Field(default=10, description="Number of results to return")
    max_results: int = Field(default=10, description="Number of results to return")
    region: str | None = None
    safesearch: str | None = None
    time: str | None = None

    # Extensions
    proxy: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    use_browser: bool = False
    headless: bool = True
    bypass_proxy_for_driver: bool = True

    # ── override endpoints ───────────────────────────────────────────────
    def _search_text(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """
        Unified dispatcher for text search with multi‑level fallback.
        """

        # tier 0 - primp 
        # ────────────────────────────────────────────────────────────────────────
        # Tier 0 — PRIMP (fast HTTP client with browser impersonation)
        # Requires: `pip install -U primp` (https://github.com/deedy5/primp)
        # Notes for massive parallel runs:
        #   • We create a fresh client per call (cookie_store=False) and close it immediately.
        #   • No global env mutation; proxy is passed directly from `self.proxy`.
        #   • Optional overrides via env: PRIMP_IMPERSONATE, PRIMP_IMPERSONATE_OS.
        try:
            import primp  # lightweight, precompiled wheels available
        
            # Map DuckDuckGo params if provided (best-effort parity with ddgs)
            _params = {"q": query}
            if self.safesearch:
                _ss = str(self.safesearch).lower()
                # DuckDuckGo html param: kp=-1 (off), 0 (moderate/default), 1 (strict)
                _params["kp"] = {"off": "-1", "moderate": "0", "safe": "1", "strict": "1"}.get(_ss, "0")
            if self.time:
                # ddgs uses d/w/m/y; DDG lite accepts df with same shorthands
                _params["df"] = self.time
            if self.region:
                # e.g., "us-en", "uk-en", etc. (best‑effort; DDG may ignore unknowns)
                _params["kl"] = self.region
        
            _imp = os.getenv("PRIMP_IMPERSONATE", "chrome_131")
            _imp_os = os.getenv("PRIMP_IMPERSONATE_OS", "windows")
        
            _client = primp.Client(
                impersonate=_imp,
                impersonate_os=_imp_os,
                proxy=self.proxy,
                timeout=12,
                cookie_store=False,       # avoid state across parallel workers
                follow_redirects=True,
            )
            try:
                # If caller supplied extra headers, apply after impersonation
                if self.headers:
                    with contextlib.suppress(Exception):
                        _client.headers_update(self.headers)
        
                _resp = _client.get("https://html.duckduckgo.com/html", params=_params, timeout=12)
                if 200 <= _resp.status_code < 300 and _resp.text:
                    from bs4 import BeautifulSoup
                    from urllib.parse import urlparse, parse_qs, unquote
        
                    _soup = BeautifulSoup(_resp.text, "html.parser")
                    _links = _soup.select("a.result__a")
                    _snips = _soup.select("div.result__snippet, a.result__snippet")
        
                    _out = []
                    _limit = int(max_results or INTERNAL_MAX_RETURN)
                    for i, a in enumerate(_links[:_limit], 1):
                        _raw = a.get("href", "")
                        _parsed = urlparse(_raw)
                        _real = unquote(parse_qs(_parsed.query).get("uddg", [_raw])[0])
        
                        _snip = ""
                        if i - 1 < len(_snips):
                            with contextlib.suppress(Exception):
                                _snip = _snips[i - 1].get_text(strip=True)
        
                        _out.append(
                            {
                                "id": i,
                                "title": a.get_text(strip=True),
                                "href": _raw,
                                "body": f"__START_OF_SOURCE {i}__ <CONTENT> {_snip} </CONTENT> <URL> {_real} </URL> __END_OF_SOURCE {i}__",
                            }
                        )
                    if _out:
                        return _out
            finally:
                # Hard cleanup for parallel safety
                with contextlib.suppress(Exception):
                    close_fn = getattr(_client, "close", None)
                    if callable(close_fn):
                        close_fn()
                del _client
        
        except Exception as _primp_exc:
            logger.debug("PRIMP tier failed: %s", _primp_exc)
        # End tier 0
        
        # Tier 1 – Selenium
        if self.use_browser:
            try:
                return _browser_search(
                    query,
                    max_results=max_results,
                    proxy=self.proxy,
                    headers=self.headers,
                    headless=self.headless,
                    bypass_proxy_for_driver=self.bypass_proxy_for_driver,
                )
            except WebDriverException as exc:
                print("Browser tier WebDriverException caught:")
                print(f"Exception: {exc}")
                print(traceback.format_exc())
                logger.warning("Browser tier failed (%s); falling back.", exc)

        print("Done with Selenium try")         

        # Tier 2 – ddgs HTTP API
        try:
            return _with_ddgs(
                self.proxy,
                self.headers,
                lambda d: list(
                    d.text(
                        query,
                        max_results=max_results,
                        region=self.region,
                        safesearch=self.safesearch,
                        timelimit=self.time,
                    )
                ),
            )
        except DDGSException as exc:
            logger.warning("ddgs tier failed (%s); falling back to raw scrape.", exc)

        # Tier 3 – raw Requests scrape
        return _requests_scrape(
            query,
            max_results=max_results,
            proxy=self.proxy,
            headers=self.headers,
        )

    # LangChain calls the four “_ddgs_*” methods – just delegate.
    def _ddgs_text(self, query: str, **kw):
        return self._search_text(query, kw.get("max_results", self.k))

    def _ddgs_images(self, query: str, **kw):
        return _with_ddgs(
            self.proxy,
            self.headers,
            lambda d: list(
                d.images(
                    query,
                    max_results=kw.get("max_results", self.k),
                    region=self.region,
                    safesearch=self.safesearch,
                    timelimit=self.time,
                )
            ),
        )

    def _ddgs_videos(self, query: str, **kw):
        return _with_ddgs(
            self.proxy,
            self.headers,
            lambda d: list(
                d.videos(
                    query,
                    max_results=kw.get("max_results", self.k),
                    region=self.region,
                    safesearch=self.safesearch,
                    timelimit=self.time,
                )
            ),
        )

    def _ddgs_news(self, query: str, **kw):
        return _with_ddgs(
            self.proxy,
            self.headers,
            lambda d: list(
                d.news(
                    query,
                    max_results=kw.get("max_results", self.k),
                    region=self.region,
                    safesearch=self.safesearch,
                    timelimit=self.time,
                )
            ),
        )

class PatchedDuckDuckGoSearchRun(DuckDuckGoSearchRun):
    """LangChain *Tool* wired to the safe API wrapper above."""
    api_wrapper: PatchedDuckDuckGoSearchAPIWrapper = Field(
        default_factory=PatchedDuckDuckGoSearchAPIWrapper
    )


# Semantic aliases for code that always picks the browser path
BrowserDuckDuckGoSearchAPIWrapper = PatchedDuckDuckGoSearchAPIWrapper
BrowserDuckDuckGoSearchRun = PatchedDuckDuckGoSearchRun

from selenium.webdriver.firefox.options import Options # Firefox 
#from selenium.webdriver.chrome.options import Options # Chrome



