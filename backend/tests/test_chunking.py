from app.kb.chunking import chunk_text


def test_chunk_text_splits_paragraphs_and_keeps_size():
    text = "\n\n".join(["第一段。" * 60, "第二段。" * 60])
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 200 + 40 for chunk in chunks)


def test_chunk_text_handles_empty_input():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_hard_wraps_without_punctuation():
    text = "a" * 1000
    chunks = chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    assert sum(len(chunk) for chunk in chunks) >= 1000
