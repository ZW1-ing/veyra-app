import { LLM } from "@/types"

/**
 * Veyra 服务（自建后端）
 *
 * 这一档不走任何模型厂商，而是把请求交给 Python 后端
 * （backend/：FastAPI + LangGraph + MySQL），由它做知识库检索、工具调用与多智能体编排。
 * 后端地址通过 VEYRA_API_URL 配置，默认 http://127.0.0.1:8000。
 */
const VEYRA_PLATFORM_LINK = "https://github.com/xiaopeng-126/veyra-app"

const VEYRA_AGENT: LLM = {
  modelId: "veyra-agent",
  modelName: "Veyra 智能体（单智能体 · 带工具）",
  provider: "veyra",
  hostedId: "veyra-agent",
  platformLink: VEYRA_PLATFORM_LINK,
  imageInput: false
}

const VEYRA_SWARM: LLM = {
  modelId: "veyra-swarm",
  modelName: "Veyra 蜂群（多智能体协作）",
  provider: "veyra",
  hostedId: "veyra-swarm",
  platformLink: VEYRA_PLATFORM_LINK,
  imageInput: false
}

export const VEYRA_LLM_LIST: LLM[] = [VEYRA_AGENT, VEYRA_SWARM]
