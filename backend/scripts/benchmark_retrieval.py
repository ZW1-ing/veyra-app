"""检索性能基准：全量余弦到什么规模才需要 ANN 索引。

为什么要有这个脚本：向量索引（pgvector / hnswlib）是「到规模才需要」的东西。
没有实测数据就引入，只是在给项目增加依赖和复杂度。
这里按不同的知识库规模量一遍延迟，用数字决定什么时候该换。

用法：
    .venv\\Scripts\\python.exe scripts\\benchmark_retrieval.py
    .venv\\Scripts\\python.exe scripts\\benchmark_retrieval.py --sizes 500,2000,10000
"""

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.kb.retrieval import cosine_scores_batch, rank_chunks  # noqa: E402

DIM = 1024


def make_candidates(count: int, dim: int = DIM) -> list[dict]:
    """造一批假分块：向量随机、文本用中文短语，尽量贴近真实的数据形态。"""
    random.seed(42)  # 固定种子，保证多次运行可比
    words = ["知识库", "检索", "智能体", "工作流", "向量", "分块", "提示词", "上下文"]
    return [
        {
            "chunk_id": f"c{index}",
            "document_id": f"d{index // 20}",
            "document_name": f"doc-{index // 20}.md",
            "chunk_index": index % 20,
            "text": "".join(random.choice(words) for _ in range(60)),
            "embedding": [random.random() for _ in range(dim)],
        }
        for index in range(count)
    ]


def time_call(func, repeat: int = 5) -> float:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        func()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description="检索性能基准")
    parser.add_argument("--sizes", default="200,1000,5000")
    parser.add_argument("--dim", type=int, default=DIM)
    args = parser.parse_args()

    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    query_vector = [random.random() for _ in range(args.dim)]
    query = "知识库 检索 智能体"

    print(f"向量维度 {args.dim}，每次检索取 Top-6，每档测 5 次取中位数\n")
    print(f"{'分块数':>8}{'纯 Python 逐条':>16}{'numpy 批量':>14}{'rank_chunks 全流程':>20}")
    print("-" * 60)

    for count in sizes:
        candidates = make_candidates(count, args.dim)
        vectors = [item["embedding"] for item in candidates]

        # 纯 Python 逐条：临时把 numpy 关掉，量出没有 numpy 时的真实耗时
        import app.kb.retrieval as retrieval

        saved = retrieval._np
        retrieval._np = None
        # 用默认参数把当轮的 vectors 绑进去：lambda 直接闭包循环变量容易被误读
        python_ms = time_call(lambda v=vectors: cosine_scores_batch(query_vector, v))
        retrieval._np = saved

        numpy_ms = time_call(lambda v=vectors: cosine_scores_batch(query_vector, v))
        full_ms = time_call(
            lambda c=candidates: rank_chunks(
                query=query,
                query_embedding=query_vector,
                candidates=c,
                top_k=6,
            )
        )

        print(f"{count:>8}{python_ms:>14.1f}ms{numpy_ms:>12.1f}ms{full_ms:>18.1f}ms")

    print("\n判读方法：")
    print("  全流程耗时 < 100ms  → 全量余弦完全够用，不需要 ANN")
    print("  100ms ~ 300ms      → 还能接受，优先加缓存或缩小候选集")
    print("  > 300ms            → 该上向量索引了（pgvector / faiss / Milvus）")


if __name__ == "__main__":
    main()
