def gemma_doc(text):
    return f"title: none | text: {text}"


def gemma_query(query):
    return f"task: search result | query: {query}"


def nomic_doc(text):
    return f"search_document: {text}"


def nomic_query(query):
    return f"search_query: {query}"


def chunk_text(text, max_chars=7000):
    text = (text or "").strip()
    if not text:
        return []
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
