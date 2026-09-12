"""
Web Research MCP Server for Microsoft UFO
Provides tools for web searches and fetching HTML/text from public URLs.
"""
import json
import logging
import urllib.request
import urllib.parse
import re
from typing import Annotated, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

def _strip_html(html_text: str) -> str:
    """Convert HTML content into clean readable plain text."""
    # Remove script and style tags
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block tags with newlines
    clean = re.sub(r"<(p|div|h[1-6]|li|br|tr)[^>]*>", "\n", clean, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Unescape common entities
    clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    # Collapse multiple whitespace
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n\s*\n+", "\n\n", clean)
    return clean.strip()

@MCPRegistry.register_factory_decorator('WebResearchExecutor')
@MCPRegistry.register_factory_decorator('web_research_mcp_server')
def create_web_research_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the Web Research MCP server instance."""
    mcp = FastMCP("UFO Web Research MCP Server")

    @mcp.tool()
    def fetch_url(
        url: Annotated[str, Field(description="The complete HTTP/HTTPS URL to fetch.")],
        max_chars: Annotated[int, Field(description="Maximum characters of extracted text to return.")]=5000,
    ) -> str:
        """Fetch content from a public URL and return cleaned markdown/plain text."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
                encoding = resp.headers.get_content_charset() or "utf-8"
                raw_html = raw_bytes.decode(encoding, errors="replace")

            text = _strip_html(raw_html)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... Truncated ({len(text) - max_chars} characters remaining) ...]"
            return text if text else "[Page returned empty body]"
        except Exception as e:
            raise ToolError(f"Failed to fetch {url}: {e}")

    @mcp.tool()
    def search_web(
        query: Annotated[str, Field(description="Search query string.")],
        max_results: Annotated[int, Field(description="Maximum search results to return.")]=5,
    ) -> str:
        """Search the web using DuckDuckGo HTML endpoint and return top result titles and URLs."""
        if not query or not query.strip():
            raise ToolError("Search query cannot be empty.")
        try:
            encoded_query = urllib.parse.urlencode({"q": query.strip()})
            search_url = f"https://html.duckduckgo.com/html/?{encoded_query}"
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Extract result snippets
            results = []
            links = re.findall(r'<a class="result__url" href="([^"]+)".*?>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)

            for i in range(min(max_results, len(links))):
                link = links[i][0].strip()
                snippet = _strip_html(titles[i]) if i < len(titles) else ""
                results.append(f"{i+1}. URL: {link}\n   Snippet: {snippet}")

            if not results:
                # Fallback simple title extraction
                simple_links = re.findall(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
                for i, (lnk, title) in enumerate(simple_links[:max_results]):
                    results.append(f"{i+1}. { _strip_html(title) }\n   URL: {lnk}")

            return "\n\n".join(results) if results else f"No search results found for query: {query}"
        except Exception as e:
            raise ToolError(f"Web search failed: {e}")

    return mcp

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_web_research_mcp_server()
    mcp.run()
