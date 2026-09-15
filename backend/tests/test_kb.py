RELATED = (
    "Veyra 是一个本地优先的 AI 工作台。"
    "它的 Agent 引擎支持工具调用循环：模型先思考，需要时调用工具，"
    "拿到结果再继续推理，最多八步。"
)
UNRELATED = "红烧肉的做法：五花肉切块，冷水下锅焯水，加冰糖炒糖色，小火炖四十分钟。"


def _ingest(client, name, text):
    response = client.post("/kb/documents", json={"name": name, "text": text})
    assert response.status_code == 201
    return response.json()


def test_ingest_accepts_custom_chunk_size(client):
    """主题密集的短文可以按更小的块入库，块数应该随之变多。"""
    text = "第一件事的说明。第二件事的说明。第三件事的说明。第四件事的说明。"
    big = _ingest(client, "big.md", text)
    small = client.post(
        "/kb/documents",
        json={"name": "small.md", "text": text, "chunk_size": 50, "chunk_overlap": 0},
    )
    assert small.status_code == 201
    assert small.json()["id"] != big["id"]


def test_ingest_and_search_ranks_related_document_first(client):
    _ingest(client, "agent.md", RELATED)
    _ingest(client, "recipe.md", UNRELATED)

    documents = client.get("/kb/documents").json()
    # 用子集断言而不是精确相等：同一个测试会话里其它用例也会往知识库写文档
    assert {"agent.md", "recipe.md"} <= {doc["name"] for doc in documents}
    assert all(doc["char_count"] > 0 for doc in documents)

    sources = client.post("/kb/search", json={"query": "Agent 工具调用循环怎么走", "top_k": 3}).json()
    assert sources, "应该至少召回一个片段"
    assert sources[0]["document_name"] == "agent.md"
    assert sources[0]["id"] == "S1"
    assert 0 < sources[0]["score"] <= 1


def test_unrelated_query_does_not_invent_sources(client):
    """知识库里只有 Agent 文档和菜谱时，问量子计算不该硬凑出引用片段。"""
    sources = client.post("/kb/search", json={"query": "量子比特的退相干时间怎么测量"}).json()
    assert sources == []


def test_ingest_records_embedding_model_and_chunk_size(client):
    """入库要留下「用哪个模型、切多大」的痕迹，否则换模型后无从排查。"""
    doc = client.post(
        "/kb/documents",
        json={"name": "meta.md", "text": "这是一段用来检查元信息记录的文字。" * 20},
    ).json()
    assert doc["chunk_size"] == 500
    assert doc["embedding_model"].startswith("hash")
    assert doc["embedding_dim"] == 128


def test_dimension_mismatch_is_skipped_instead_of_scored_as_zero():
    """维度对不上时必须剔除，不能静默按 0 分处理。"""
    from app.kb.service import _drop_dimension_mismatch

    candidates = [
        {"chunk_id": "a", "embedding": [0.1] * 64},
        {"chunk_id": "b", "embedding": [0.1] * 128},
        {"chunk_id": "c", "embedding": None},
    ]
    kept, skipped = _drop_dimension_mismatch(candidates, query_dim=128)

    assert skipped == 1
    assert {item["chunk_id"] for item in kept} == {"b", "c"}
