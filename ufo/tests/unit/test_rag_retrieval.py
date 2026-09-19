"""RAG retrieval: FAISS round-trip (writer format == reader format), keyless
DuckDuckGo parsing, search-backend selection and data-path resolution."""
import os
from unittest import mock

import pytest

pytest.importorskip("faiss")

from langchain_community.embeddings import DeterministicFakeEmbedding
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from ufo.rag import ddg_search, retriever, web_search
from ufo.utils import resolve_data_path

EMB = DeterministicFakeEmbedding(size=32)

HTML_PAGE = """
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsupport.microsoft.com%2Ftoc&amp;rut=abc">Insert a <b>table of contents</b></a>
  </h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Go to <b>References</b> &gt; Table of Contents.</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_provider=bing">Sponsored</a>
  <a class="result__snippet" href="#">ad</a>
</div>
<div class="result">
  <a rel="nofollow" class="result__a" href="https://example.org/word-toc">Word TOC guide</a>
  <a class="result__snippet" href="#">Step by step.</a>
</div>
"""

LITE_PAGE = """
<table>
<tr><td><a rel="nofollow" href="https://example.com/a" class='result-link'>First &amp; best</a></td></tr>
<tr><td class='result-snippet'>Snippet <b>one</b></td></tr>
<tr><td><a rel="nofollow" href="https://example.com/b" class='result-link'>Second</a></td></tr>
<tr><td class='result-snippet'>Snippet two</td></tr>
</table>
"""

CHALLENGE_PAGE = '<html><form id="challenge-form" action="/anomaly.js"></form></html>'


def test_parse_html_results_unwraps_redirects_and_skips_ads():
    results = ddg_search.parse_results(HTML_PAGE, max_results=5)
    assert [r["url"] for r in results] == [
        "https://support.microsoft.com/toc",
        "https://example.org/word-toc",
    ]
    assert results[0]["name"] == "Insert a table of contents"
    assert results[0]["snippet"] == "Go to References > Table of Contents."


def test_parse_lite_results():
    results = ddg_search.parse_results(LITE_PAGE, max_results=1)
    assert results == [{"name": "First & best", "url": "https://example.com/a", "snippet": "Snippet one"}]


def test_search_falls_back_to_lite_and_fails_soft():
    pages = {ddg_search.DDG_URL: CHALLENGE_PAGE, ddg_search.DDG_LITE_URL: LITE_PAGE}
    with mock.patch.object(ddg_search, "_post", side_effect=lambda url, q, t: pages[url]):
        assert [r["url"] for r in ddg_search.search("q", 5)] == ["https://example.com/a", "https://example.com/b"]
    with mock.patch.object(ddg_search, "_post", return_value=CHALLENGE_PAGE):
        assert ddg_search.search("q", 5) == []
    assert ddg_search.search("   ") == []
    assert ddg_search.is_challenge(CHALLENGE_PAGE)


@pytest.mark.parametrize(
    "key, expected",
    [("${BING_API_KEY}", web_search.DuckDuckGoSearchWeb), ("", web_search.DuckDuckGoSearchWeb),
     ("real-key", web_search.BingSearchWeb)],
)
def test_search_backend_selection(key, expected):
    fake_cfg = mock.Mock()
    fake_cfg.rag.bing_api_key = key
    with mock.patch.object(web_search, "ufo_config", fake_cfg):
        assert type(web_search.get_search_web()) is expected


def test_create_documents_handles_none():
    assert web_search.DuckDuckGoSearchWeb().create_documents(None) == []


def test_experience_index_round_trip(tmp_path):
    db_path = str(tmp_path / "experience_db")
    docs = [
        Document(page_content="save the document as report.docx", metadata={"request": "save", "Tips": "use F12"}),
        Document(page_content="bold the title in word", metadata={"request": "bold", "Tips": "ctrl+b"}),
    ]
    FAISS.from_documents(docs, EMB).save_local(db_path)
    with mock.patch.object(retriever, "get_hugginface_embedding", return_value=EMB):
        r = retriever.RetrieverFactory.create_retriever("experience", db_path)
        hits = r.retrieve("bold the title in word", 1)
    assert hits and hits[0].metadata["Tips"] == "ctrl+b"


def test_missing_index_returns_empty(tmp_path):
    with mock.patch.object(retriever, "get_hugginface_embedding", side_effect=AssertionError("not loaded")):
        r = retriever.RetrieverFactory.create_retriever("demonstration", str(tmp_path / "nope"))
    assert r.indexer is None and r.retrieve("anything", 3) == []


def test_online_retriever_indexes_search_results():
    backend = web_search.DuckDuckGoSearchWeb()
    page_docs = [Document(page_content="References > Table of Contents > Automatic Table", metadata={})]
    with mock.patch.object(web_search, "get_search_web", return_value=backend), \
         mock.patch.object(backend, "search", return_value=[{"name": "n", "url": "https://e.com", "snippet": "s"}]), \
         mock.patch.object(backend, "get_url_text", return_value=page_docs), \
         mock.patch.object(web_search, "get_hugginface_embedding", return_value=EMB):
        r = retriever.RetrieverFactory.create_retriever("online", "insert toc", 1)
        hits = r.retrieve("insert toc", 1)
    assert hits[0].metadata["url"] == "https://e.com"


def test_online_retriever_no_results():
    backend = web_search.DuckDuckGoSearchWeb()
    with mock.patch.object(web_search, "get_search_web", return_value=backend), \
         mock.patch.object(backend, "search", return_value=[]):
        assert retriever.RetrieverFactory.create_retriever("online", "q", 1).indexer is None


def test_resolve_data_path():
    assert resolve_data_path("") == ""
    absolute = os.path.abspath("x")
    assert resolve_data_path(absolute) == absolute
    resolved = resolve_data_path("vectordb/experience/")
    assert os.path.isabs(resolved) and resolved.endswith(os.path.join("vectordb", "experience"))
    # Anchored at the directory containing the ufo package (the launch directory).
    import ufo
    assert os.path.dirname(os.path.dirname(os.path.abspath(ufo.__file__))) in resolved
