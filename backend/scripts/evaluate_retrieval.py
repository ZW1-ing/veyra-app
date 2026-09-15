"""检索质量评估：用带标注的小数据集量化 recall@k、MRR 和误召回率。

为什么需要它：
调整分块大小、换嵌入模型、改混合权重都会影响检索效果，靠"感觉好像准了"是不可靠的。
这个脚本把效果变成数字，改完前后各跑一次就能判断改动是否真的有价值。

用法：
    .venv\\Scripts\\python.exe scripts\\evaluate_retrieval.py
    .venv\\Scripts\\python.exe scripts\\evaluate_retrieval.py --embedding openai_compat --model nomic-embed-text
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db import models  # noqa: E402,F401  注册表结构
from app.db.base import Base  # noqa: E402
from app.kb.embedding import HashEmbedding, OpenAICompatEmbedding  # noqa: E402
from app.kb.service import ingest_document, search_knowledge  # noqa: E402

# 语料：刻意写成「问法和原文用词不一样」，这样才能测出语义检索是否真的有用，
# 只会背关键词的词法检索在这个数据集上会明显吃亏。
CORPUS: list[tuple[str, str]] = [
    (
        "agent-loop.md",
        "Agent 引擎采用工具调用循环：模型先思考，需要时调用工具，拿到结果继续推理。"
        "为避免死循环，单轮最多允许八步工具调用，超过上限就基于已有信息作答。",
    ),
    (
        "swarm.md",
        "多智能体模式下由 Leader 负责拆解任务并分配给成员，调度器按依赖关系决定执行顺序，"
        "同时运行的成员数量受并发上限约束，默认是两个。",
    ),
    (
        "storage.md",
        "会话与消息全部持久化到 MySQL，使用 SQLAlchemy 作为 ORM，表结构通过 Alembic 迁移管理。"
        "开发环境允许自动建表，生产环境必须走迁移。",
    ),
    (
        "provider.md",
        "模型后端统一走 OpenAI 兼容协议，因此 DeepSeek、豆包方舟、本地 Ollama 可以共用一份实现。"
        "如果缺少密钥，服务会自动降级到离线 mock 模型，保证演示和测试不受影响。",
    ),
    (
        "retrieval.md",
        "知识库检索采用混合策略：词法部分用中文分词加 IDF 加权，向量部分用余弦相似度，"
        "两者加权求和。还要求命中覆盖率达标，避免给无关问题硬凑引用。",
    ),
    (
        "streaming.md",
        "流式接口通过 SSE 逐字返回，响应在接口函数返回之后才写出，"
        "因此落库时必须另开一个短会话，否则会遇到会话已关闭的问题。",
    ),
    (
        "deploy.md",
        "服务用 Docker 部署，docker compose 一条命令拉起应用和数据库；"
        "镜像里用非 root 用户运行，并通过 healthcheck 探活。",
    ),
    (
        "unrelated-pasta.md",
        "番茄意面的做法：橄榄油炒香蒜片，加入番茄翻炒出沙，放入煮好的意面拌匀，撒罗勒叶。",
    ),
]

# (问题, 期望命中的文档)；期望为 None 表示知识库里没有答案，不该召回任何片段
QUERIES: list[tuple[str, str | None]] = [
    ("模型最多能连续调用几次工具？", "agent-loop.md"),
    ("一次任务里可以派几个小助手同时干活？", "swarm.md"),
    ("对话记录存在哪里？", "storage.md"),
    ("没有配置 API Key 的时候服务会怎么样？", "provider.md"),
    ("怎么防止给不相关的问题乱加引用？", "retrieval.md"),
    ("为什么回答能一个字一个字蹦出来？", "streaming.md"),
    ("部署的时候需要手动装数据库吗？", "deploy.md"),
    ("用什么工具管理数据库表结构的变更？", "storage.md"),
    ("红烧牛肉要炖多久？", None),
    ("明天北京的天气怎么样？", None),
    ("量子纠缠为什么不能用来超光速通信？", None),
    ("推荐几部科幻电影", None),
]


def build_embedding(args) -> object:
    if args.embedding == "openai_compat":
        provider = OpenAICompatEmbedding(
            base_url=args.base_url, model=args.model, api_key=args.api_key, dim=args.dim
        )
    else:
        provider = HashEmbedding(dim=args.dim)
    return CachedEmbedding(provider)


class CachedEmbedding:
    """给嵌入调用加缓存。

    参数扫描要跑几十种配置，重复调用真实模型会非常慢，
    而同一段文本的向量是确定的，缓存下来能省掉绝大多数等待。
    """

    def __init__(self, provider):
        self.provider = provider
        self.dim = getattr(provider, "dim", 0)
        self._cache: dict[str, list[float]] = {}

    async def embed(self, texts):
        results: list[list[float] | None] = [self._cache.get(text) for text in texts]
        pending = [text for text, vector in zip(texts, results, strict=True) if vector is None]
        if pending:
            fresh = await self.provider.embed(pending)
            fresh_iter = iter(fresh)
            for index, vector in enumerate(results):
                if vector is None:
                    vector = next(fresh_iter)
                    results[index] = vector
                    self._cache[texts[index]] = vector
        return results


def make_settings(args, **overrides) -> Settings:
    values = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "embedding_dim": args.dim,
        "retrieval_top_k": args.top_k,
        "lexical_weight": args.lexical_weight,
        "vector_weight": args.vector_weight,
        "retrieval_min_score": args.min_score,
        "retrieval_min_coverage": args.min_coverage,
        "retrieval_min_vector_similarity": args.min_vector_similarity,
    }
    values.update(overrides)
    return Settings(**values)


async def prepare_corpus(db: Session, embedding, settings: Settings) -> None:
    for name, text in CORPUS:
        await ingest_document(db, embedding, settings, name=name, text=text)


async def evaluate(db: Session, embedding, settings: Settings) -> dict:
    hits = 0
    reciprocal_ranks: list[float] = []
    answerable = 0
    false_positives = 0
    unanswerable = 0
    rows: list[tuple[str, str, int | None, int]] = []

    for query, expected in QUERIES:
        sources = await search_knowledge(db, embedding, settings, query)
        rank = next(
            (index + 1 for index, source in enumerate(sources) if source.document_name == expected),
            None,
        )
        if expected:
            answerable += 1
            if rank:
                hits += 1
                reciprocal_ranks.append(1.0 / rank)
            else:
                reciprocal_ranks.append(0.0)
        else:
            unanswerable += 1
            if sources:
                false_positives += 1
        rows.append((query, expected or "（应无结果）", rank, len(sources)))

    return {
        "rows": rows,
        "recall": hits / answerable if answerable else 0.0,
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "false_positive_rate": false_positives / unanswerable if unanswerable else 0.0,
        "answerable": answerable,
        "unanswerable": unanswerable,
    }


async def evaluate_once(args) -> dict:
    settings = make_settings(args)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    embedding = build_embedding(args)

    with Session(engine) as db:
        await prepare_corpus(db, embedding, settings)
        return await evaluate(db, embedding, settings)


async def sweep(args) -> None:
    """扫描阈值组合，找一个「召回不掉、误召回尽量低」的工作点。

    如果扫完发现没有任何组合能同时满足「召回达标」和「零误召回」，
    这本身就是结论：瓶颈不在阈值，得先动嵌入模型或分块方式。
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    embedding = build_embedding(args)
    scores = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]
    coverages = [0.05, 0.10, 0.15, 0.25]
    vector_floors = [0.0, 0.35, 0.45, 0.55]
    recall_target = 0.875

    with Session(engine) as db:
        base = make_settings(args)
        await prepare_corpus(db, embedding, base)

        print(f"召回目标 >= {recall_target:.1%}")
        print(
            f"{'min_score':>10}{'min_cov':>9}{'min_vec':>9}"
            f"{'recall':>10}{'MRR':>8}{'误召回':>10}   评价"
        )
        print("-" * 76)
        viable: list[tuple[float, float, float]] = []
        best_by_fp: tuple[float, float, float, float] | None = None
        for min_score in scores:
            for min_coverage in coverages:
                for min_vector in vector_floors:
                    settings = make_settings(
                        args,
                        retrieval_min_score=min_score,
                        retrieval_min_coverage=min_coverage,
                        retrieval_min_vector_similarity=min_vector,
                    )
                    result = await evaluate(db, embedding, settings)
                    fp = result["false_positive_rate"]
                    ok = result["recall"] >= recall_target
                    if ok and fp == 0:
                        mark = "✔ 推荐"
                        viable.append((fp, min_score, min_coverage))
                    elif ok:
                        mark = "召回够但有误召回"
                    else:
                        mark = "召回受损"
                    print(
                        f"{min_score:>10.2f}{min_coverage:>9.2f}{min_vector:>9.2f}"
                        f"{result['recall']:>9.1%}{result['mrr']:>8.3f}"
                        f"{fp:>9.1%}   {mark}"
                    )
                    if ok and (best_by_fp is None or fp < best_by_fp[0]):
                        best_by_fp = (fp, min_score, min_coverage, min_vector)

        print("-" * 76)
        if viable:
            # 多个可用组合时，取阈值更宽松的那个，留出泛化余量
            _, min_score, min_coverage = max(viable, key=lambda item: (item[1], item[2]))
            print(f"建议：RETRIEVAL_MIN_SCORE={min_score}  RETRIEVAL_MIN_COVERAGE={min_coverage}（零误召回）")
        elif best_by_fp:
            print(
                f"结论：没有任何阈值组合能同时做到「召回 >= {recall_target:.0%}」和「零误召回」。\n"
                f"      最好的组合（min_score={best_by_fp[1]}, min_coverage={best_by_fp[2]}, "
                f"min_vector={best_by_fp[3]}）仍有 {best_by_fp[0]:.0%} 误召回。\n"
                f"      说明瓶颈不在阈值，先去解决嵌入质量或分块方式，别继续调阈值。"
            )
        else:
            print(f"结论：所有组合的召回都低于 {recall_target:.0%}，检索链路本身需要排查。")


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量评估")
    parser.add_argument("--embedding", default="hash", choices=["hash", "openai_compat"])
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--dim", type=int, default=256)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--lexical-weight", type=float, default=0.6)
    parser.add_argument("--vector-weight", type=float, default=0.4)
    parser.add_argument("--min-score", type=float, default=0.10)
    parser.add_argument("--min-coverage", type=float, default=0.15)
    parser.add_argument("--min-vector-similarity", type=float, default=0.45)
    parser.add_argument("--sweep", action="store_true", help="扫描阈值组合，找更优工作点")
    args = parser.parse_args()

    if args.sweep:
        asyncio.run(sweep(args))
        return

    result = asyncio.run(evaluate_once(args))

    print(f"嵌入方式：{args.embedding}   top_k={args.top_k}   词法/向量权重={args.lexical_weight}/{args.vector_weight}")
    print("-" * 78)
    print(f"{'查询':<34}{'期望命中':<20}{'实际排名':>8}")
    print("-" * 78)
    for query, expected, rank, source_count in result["rows"]:
        if expected == "（应无结果）":
            shown = f"召回 {source_count} 条" + ("（应为 0）" if source_count else " ✓")
        else:
            shown = "未召回" if rank is None else f"第 {rank} 位"
        print(f"{query:<34}{expected:<20}{shown:>8}")
    print("-" * 78)
    print(f"recall@{args.top_k}：{result['recall']:.1%}（{result['answerable']} 个可回答问题）")
    print(f"MRR：{result['mrr']:.3f}")
    print(f"误召回率：{result['false_positive_rate']:.1%}（{result['unanswerable']} 个无答案问题）")


if __name__ == "__main__":
    main()
