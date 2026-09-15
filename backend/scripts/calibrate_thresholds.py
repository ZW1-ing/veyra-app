"""校准检索阈值：跑一批标注过的查询，看相关与无关样本的分数分布落在哪里。

为什么需要它：阈值拍脑袋定，要么召不回相关内容，要么给无关问题硬凑引用。
这个脚本把两个分布打印出来，取中间的空隙当阈值，并把结果写进 .env。

用法：
    .venv\\Scripts\\python.exe scripts\\calibrate_thresholds.py
"""

import asyncio
import statistics
import sys
from pathlib import Path

# 允许直接用 `python scripts/xxx.py` 运行：把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.kb.embedding import HashEmbedding
from app.kb.retrieval import build_idf, lexical_score, rank_chunks

# 两个分块，模拟真实知识库：一个技术文档，一个完全无关的文档
CANDIDATES = [
    {
        "chunk_id": "c1",
        "document_id": "d1",
        "document_name": "veyra-agent.md",
        "chunk_index": 0,
        "text": (
            "Veyra 的 Agent 引擎采用工具调用循环：模型先思考，需要时调用工具，"
            "拿到结果继续推理，最多八步。多智能体模式下由 Leader 规划任务并分配给成员。"
        ),
    },
    {
        "chunk_id": "c2",
        "document_id": "d2",
        "document_name": "recipe.md",
        "chunk_index": 0,
        "text": "红烧肉的做法：五花肉切块，冷水下锅焯水，加冰糖炒糖色，小火炖四十分钟。",
    },
]

# (查询, 期望命中的文档名)；期望为 None 表示「知识库里没有相关内容」
QUERIES = [
    ("Agent 工具调用循环最多几步", "veyra-agent.md"),
    ("Veyra 的 Agent 最多几轮工具调用？", "veyra-agent.md"),
    ("Veyra 的 Agent 最多几轮工具调用？回答控制在两句话内。", "veyra-agent.md"),
    ("红烧肉怎么做", "recipe.md"),
    ("量子比特的退相干时间怎么测量", None),
    ("今天上海的天气预报", None),
]


async def main() -> None:
    embedding = HashEmbedding(dim=128)
    idf_map = build_idf(CANDIDATES)

    print(f"{'查询':<44} {'最高分':>8} {'覆盖率':>8}  期望")
    print("-" * 76)

    relevant_scores: list[float] = []
    relevant_coverages: list[float] = []
    irrelevant_scores: list[float] = []
    irrelevant_coverages: list[float] = []

    for query, expected in QUERIES:
        vector = (await embedding.embed([query]))[0]
        ranked = rank_chunks(
            query, vector, CANDIDATES, top_k=1, min_score=0.0, min_coverage=0.0
        )
        if not ranked:
            print(f"{query:<44} {'-':>8} {'-':>8}  {expected}")
            continue
        top = ranked[0]
        _, coverage = lexical_score(query, top.document_name, top.text, idf_map)
        mark = "命中" if expected and top.document_name == expected else ("未命中" if expected else "")
        print(
            f"{query:<44} {top.score:>8.3f} {coverage:>8.3f}  "
            f"{expected or '无相关内容'} {mark}"
        )

        if expected:
            relevant_scores.append(top.score)
            relevant_coverages.append(coverage)
        else:
            irrelevant_scores.append(top.score)
            irrelevant_coverages.append(coverage)

    print("-" * 76)
    print(f"相关样本  得分 {min(relevant_scores):.3f} ~ {max(relevant_scores):.3f}"
          f"（中位 {statistics.median(relevant_scores):.3f}）"
          f"  覆盖率 {min(relevant_coverages):.3f} ~ {max(relevant_coverages):.3f}")
    print(f"无关样本  得分 {min(irrelevant_scores):.3f} ~ {max(irrelevant_scores):.3f}"
          f"  覆盖率 {min(irrelevant_coverages):.3f} ~ {max(irrelevant_coverages):.3f}")
    print()
    print("建议：阈值取两个分布中间的空隙，例如")
    print(f"  RETRIEVAL_MIN_SCORE={round((max(irrelevant_scores) + min(relevant_scores)) / 2, 2)}")
    print(f"  RETRIEVAL_MIN_COVERAGE={round((max(irrelevant_coverages) + min(relevant_coverages)) / 2, 2)}")


if __name__ == "__main__":
    asyncio.run(main())
