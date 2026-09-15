import { SidebarCreateItem } from "@/components/sidebar/items/all/sidebar-create-item"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ChatbotUIContext } from "@/context/context"
import { MODEL_NAME_MAX } from "@/db/limits"
import { TablesInsert } from "@/supabase/types"
import { FC, useContext, useState } from "react"

interface CreateModelProps {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
}

export const CreateModel: FC<CreateModelProps> = ({ isOpen, onOpenChange }) => {
  const { profile, selectedWorkspace } = useContext(ChatbotUIContext)

  const [isTyping, setIsTyping] = useState(false)

  const [apiKey, setApiKey] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [description, setDescription] = useState("")
  const [modelId, setModelId] = useState("")
  const [name, setName] = useState("")
  const [contextLength, setContextLength] = useState(4096)

  if (!profile || !selectedWorkspace) return null

  return (
    <SidebarCreateItem
      contentType="models"
      isOpen={isOpen}
      isTyping={isTyping}
      onOpenChange={onOpenChange}
      createState={
        {
          user_id: profile.user_id,
          api_key: apiKey,
          base_url: baseUrl,
          description,
          context_length: contextLength,
          model_id: modelId,
          name
        } as TablesInsert<"models">
      }
      renderInputs={() => (
        <>
          <div className="space-y-1.5 text-sm">
            <div>创建自定义模型。</div>

            <div>
              你的 API <span className="font-bold">必须</span>兼容 OpenAI SDK。
            </div>
          </div>

          <div className="space-y-1">
            <Label>名称</Label>

            <Input
              placeholder="模型名称..."
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={MODEL_NAME_MAX}
            />
          </div>

          <div className="space-y-1">
            <Label>模型 ID</Label>

            <Input
              placeholder="模型 ID..."
              value={modelId}
              onChange={e => setModelId(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <Label>接口地址</Label>

            <Input
              placeholder="接口地址..."
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
            />

            <div className="pt-1 text-xs italic">
              Your API must be compatible with the OpenAI SDK.
            </div>
          </div>

          <div className="space-y-1">
            <Label>API Key</Label>

            <Input
              type="password"
              placeholder="API Key..."
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <Label>最大上下文长度</Label>

            <Input
              type="number"
              placeholder="4096"
              min={0}
              value={contextLength}
              onChange={e => setContextLength(parseInt(e.target.value))}
            />
          </div>
        </>
      )}
    />
  )
}
