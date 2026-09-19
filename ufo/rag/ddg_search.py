"""
Keyless web search via the DuckDuckGo HTML endpoint.

Shared by the RAG online retriever and the web-research MCP server.
"""
import html as html_lib
import logging
import re
import urllib.parse
import urllib.request
from typing import Dict, List

logger = logging.getLogger(__name__)

DDG_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

_RESULT_A = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_SNIPPET = re.compile(r'<a[^>]+class="result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
# lite.duckduckgo.com markup: <a rel="nofollow" href="URL" class='result-link'>
_LITE_A = re.compile(
    r"""<a[^>]+href=["']([^"']+)["'][^>]*class=["']result-link["'][^>]*>(.*?)</a>""", re.DOTALL
)
_LITE_SNIPPET = re.compile(r"""<td[^>]+class=["']result-snippet["'][^>]*>(.*?)</td>""", re.DOTALL)


def strip_html(text: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def resolve_result_url(href: str) -> str:
    """DDG wraps result links as //duckduckgo.com/l/?uddg=<encoded target>."""
    href = html_lib.unescape(href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def parse_results(page: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Parse a DDG HTML results page into [{name, url, snippet}]."""
    links = _RESULT_A.findall(page or "")
    snippets = _SNIPPET.findall(page or "")
    if not links:
        links = _LITE_A.findall(page or "")
        snippets = _LITE_SNIPPET.findall(page or "")
    results = []
    for i, (href, title) in enumerate(links):
        url = resolve_result_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        # Skip sponsored results (they route through duckduckgo.com/y.js).
        if urllib.parse.urlparse(url).netloc.endswith("duckduckgo.com"):
            continue
        results.append(
            {
                "name": strip_html(title),
                "url": url,
                "snippet": strip_html(snippets[i]) if i < len(snippets) else "",
            }
        )
        if len(results) >= max_results:
            break
    return results


def is_challenge(page: str) -> bool:
    """DDG answers rate-limited clients with a bot-check page (HTTP 202)."""
    return "anomaly" in (page or "") and "result__a" not in page and "result-link" not in page


def _post(url: str, query: str, timeout: float) -> str:
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search(query: str, max_results: int = 5, timeout: float = 15) -> List[Dict[str, str]]:
    """Top results for query. Returns [] when DDG rate-limits this client."""
    query = (query or "").strip()
    if not query:
        return []
    for url in (DDG_URL, DDG_LITE_URL):
        page = _post(url, query, timeout)
        results = parse_results(page, max_results)
        if results:
            return results
        if is_challenge(page):
            logger.warning(f"DuckDuckGo returned a bot check from {url}.")
    return []
