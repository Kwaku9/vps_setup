import importlib.util
import pathlib

# load tools/fedora-gpu-embed/embed_recall_delta.py as a module (no package)
_p = pathlib.Path(__file__).resolve().parent.parent / "fedora-gpu-embed" / "embed_recall_delta.py"
_spec = importlib.util.spec_from_file_location("embed_recall_delta", _p)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_gemma_doc_prefix():
    assert m.gemma_doc("hello") == "title: none | text: hello"


def test_vec_literal_six_decimals():
    assert m.vec_literal([0.1, -0.25]) == "[0.100000,-0.250000]"


def test_chunk_text_splits_on_size_and_strips():
    assert m.chunk_text("  abcdef  ", n=3) == ["abc", "def"]


def test_chunk_text_empty_is_empty_list():
    assert m.chunk_text("   ") == []
