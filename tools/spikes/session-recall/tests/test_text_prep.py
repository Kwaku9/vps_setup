from text_prep import gemma_doc, gemma_query, nomic_doc, nomic_query, chunk_text


def test_gemma_prefixes():
    assert gemma_doc("hello") == "title: none | text: hello"
    assert gemma_query("find x") == "task: search result | query: find x"


def test_nomic_prefixes():
    assert nomic_doc("hello") == "search_document: hello"
    assert nomic_query("find x") == "search_query: find x"


def test_chunk_empty_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_short_text_single_chunk():
    assert chunk_text("abc", max_chars=10) == ["abc"]


def test_chunk_long_text_splits():
    chunks = chunk_text("x" * 25, max_chars=10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]
    assert all(len(c) <= 10 for c in chunks)
