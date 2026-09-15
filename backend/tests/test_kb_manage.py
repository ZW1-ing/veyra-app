"""知识库管理：重复入库去重、删除文档。"""

UNIQUE_TEXT = "这是一篇用于验证去重与删除的文档，内容独一无二：量子退火与模拟退火的关系。"


def _post_document(client, **overrides):
    payload = {"name": "dedup.md", "text": UNIQUE_TEXT}
    payload.update(overrides)
    response = client.post("/kb/documents", json=payload)
    assert response.status_code == 201
    return response.json()


def test_ingesting_same_content_twice_is_idempotent(client):
    first = _post_document(client)
    second = _post_document(client, name="换个名字.md")

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["id"] == first["id"], "内容相同就该复用同一条记录"

    ids = [item["id"] for item in client.get("/kb/documents").json()]
    assert ids.count(first["id"]) == 1, "去重之后库里不应该出现两条同内容记录"


def test_same_content_with_different_chunk_size_is_reingested(client):
    """内容一样但分块配置变了，必须重新入库，否则用户改分块会静默失效。"""
    first = _post_document(client, chunk_size=500)
    second = _post_document(client, chunk_size=50, chunk_overlap=0)

    assert second["deduplicated"] is False
    assert second["id"] != first["id"]
    assert second["chunk_size"] == 50


def test_delete_document_removes_it_and_its_chunks(client):
    from sqlalchemy import func, select

    from app.db.models import ChunkRow

    document = _post_document(client, text=UNIQUE_TEXT + "删除用例专用内容。")

    deleted = client.delete(f"/kb/documents/{document['id']}")
    assert deleted.status_code == 204

    remaining = {item["id"] for item in client.get("/kb/documents").json()}
    assert document["id"] not in remaining

    # 分块也必须一起删掉，否则检索还会捞到孤儿片段
    from app.db.session import get_session_factory

    with get_session_factory()() as db:
        left = db.execute(
            select(func.count()).select_from(ChunkRow).where(ChunkRow.document_id == document["id"])
        ).scalar_one()
    assert left == 0


def test_delete_missing_document_returns_404(client):
    assert client.delete("/kb/documents/not-exists").status_code == 404
