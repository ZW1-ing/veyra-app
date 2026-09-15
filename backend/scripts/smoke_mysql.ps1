# 端到端冒烟：服务启动后（默认 127.0.0.1:8000）依次验证健康检查、知识库入库/检索、对话落库。
param(
  [string]$Base = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

function Invoke-JsonPost([string]$Path, [hashtable]$Payload) {
  $json = $Payload | ConvertTo-Json -Depth 6
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
  return Invoke-RestMethod -Uri "$Base$Path" -Method Post -Body $bytes -ContentType "application/json; charset=utf-8"
}

Write-Output "== 1. 健康检查"
$health = Invoke-RestMethod -Uri "$Base/health"
Write-Output ("   状态={0} 数据库={1} 模型后端={2} 模型={3}" -f $health.status, $health.database, $health.provider, $health.model)

Write-Output "== 2. 知识库入库"
$doc = Invoke-JsonPost "/kb/documents" @{
  name = "veyra-agent.md"
  text = "Veyra 的 Agent 引擎采用工具调用循环：模型先思考，需要时调用工具，拿到结果继续推理，最多八步。多智能体模式下由 Leader 规划任务并分配给成员。"
}
Write-Output ("   文档 id={0} 字数={1}" -f $doc.id, $doc.char_count)

Write-Output "== 3. 知识库检索"
$sources = Invoke-JsonPost "/kb/search" @{ query = "Agent 工具调用循环最多几步"; top_k = 3 }
if ($sources.Count -eq 0) { Write-Output "   没有召回（异常）" } else {
  foreach ($s in $sources) {
    Write-Output ("   [{0}] {1} 分数={2}" -f $s.id, $s.document_name, $s.score)
  }
}

Write-Output "== 4. 对话（会用到知识库）"
$chat = Invoke-JsonPost "/chat" @{ message = "Veyra 的 Agent 最多几轮工具调用？" }
Write-Output ("   会话 id={0}" -f $chat.session_id)
Write-Output ("   回答：{0}" -f $chat.text)
Write-Output ("   引用片段数={0} 工具调用={1}" -f $chat.sources.Count, ($chat.tool_calls -join ","))

Write-Output "== 5. 消息落库检查"
$messages = Invoke-RestMethod -Uri "$Base/sessions/$($chat.session_id)/messages"
Write-Output ("   消息条数={0} 角色序列={1}" -f $messages.Count, (($messages | ForEach-Object { $_.role }) -join " -> "))

Write-Output "SMOKE RESULT: OK"
