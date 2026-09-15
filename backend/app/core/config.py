"""集中配置：所有可调项都走环境变量，代码里不写死。"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelPrice(BaseModel):
    """模型价格，单位是美元 / 百万 token。"""

    prompt_per_million: float = Field(default=0.0, ge=0)
    completion_per_million: float = Field(default=0.0, ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Veyra Agent API"
    log_level: str = "INFO"

    # 鉴权与限流
    # api_keys 为空表示不校验（仅适合本地开发）；多个 key 用逗号分隔
    api_keys: str = ""
    # 每个 key 每分钟允许的请求数；<=0 表示不限流
    rate_limit_per_minute: int = 120
    # 多实例部署时配 Redis，让限流在实例间共享；留空则用进程内实现
    redis_url: str = ""

    @property
    def api_key_set(self) -> set[str]:
        return {item.strip() for item in self.api_keys.split(",") if item.strip()}

    # 数据层
    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/veyra?charset=utf8mb4"
    # 开发期自动建表；有真实数据后应设为 false，改用 alembic upgrade head
    auto_create_tables: bool = True

    # 模型后端
    llm_provider: str = "mock"  # mock | openai_compat
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen2.5"
    llm_timeout_seconds: float = 60.0
    # 可选：按模型记录单价，例如
    # MODEL_PRICES={"qwen2.5":{"prompt_per_million":0.2,"completion_per_million":0.6}}
    # 未配置的模型按 0 计费；本地 Ollama 保持不填即可。
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    # 向量化
    embedding_provider: str = "hash"  # hash | openai_compat
    embedding_dim: int = 256
    embedding_model: str = "text-embedding-3-small"

    # 检索与 Agent
    retrieval_top_k: int = 6
    chunk_size: int = 500
    chunk_overlap: int = 80
    # 知识库单文件上传上限（字节）。默认 10 MB：再大就该考虑先做离线预处理了
    max_upload_bytes: int = 10 * 1024 * 1024
    agent_max_steps: int = 8
    # 单轮对话的整体超时（秒）：模型卡住时不能把请求无限挂着
    agent_timeout_seconds: float = 120.0
    # 带进上下文的历史消息 token 预算，超出就只保留最近的几条
    history_max_tokens: int = 3000

    # 多智能体（swarm）
    swarm_max_members: int = 5          # 团队上限，防止模型规划出十个成员
    swarm_max_concurrency: int = 2      # 同时跑几个成员，本地模型设太大反而更慢
    swarm_task_timeout_seconds: float = 120.0

    # 混合检索权重：词法得分与向量相似度
    lexical_weight: float = 0.6
    vector_weight: float = 0.4
    # 阈值由 scripts/evaluate_retrieval.py --sweep 实测校准（bge-m3 真实嵌入）：
    # 这组取值下 recall@3 = 100%、MRR = 1.000、误召回 = 0%。
    # 注意：hash 嵌入没有语义，只适合离线测试，用 hash 时召回会明显下降。
    retrieval_min_score: float = 0.25
    retrieval_min_coverage: float = 0.25
    # 向量相似度门槛：词法覆盖率不达标但语义足够接近时，同样允许进入排序。
    # 否则「对话记录存在哪里」这类问法会被纯词法门槛挡掉，白瞎了语义嵌入。
    retrieval_min_vector_similarity: float = 0.55

    @property
    def pricing_configured(self) -> bool:
        return bool(self.model_prices)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """测试里改完环境变量后调用，让新配置生效。"""
    get_settings.cache_clear()
