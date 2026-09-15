import { useChatHandler } from "@/components/chat/chat-hooks/use-chat-handler"
import { ChatbotUIContext } from "@/context/context"
import { IconInfoCircle, IconMessagePlus } from "@tabler/icons-react"
import { FC, useContext } from "react"
import { WithTooltip } from "../ui/with-tooltip"

interface ChatSecondaryButtonsProps {}

export const ChatSecondaryButtons: FC<ChatSecondaryButtonsProps> = ({}) => {
  const { selectedChat } = useContext(ChatbotUIContext)

  const { handleNewChat } = useChatHandler()

  return (
    <>
      {selectedChat && (
        <>
          <WithTooltip
            delayDuration={200}
            display={
              <div>
                <div className="text-xl font-bold">对话信息</div>

                <div className="mx-auto mt-2 max-w-xs space-y-2 sm:max-w-sm md:max-w-md lg:max-w-lg">
                  <div>模型：{selectedChat.model}</div>
                  <div>提示词：{selectedChat.prompt}</div>

                  <div>温度：{selectedChat.temperature}</div>
                  <div>上下文长度：{selectedChat.context_length}</div>

                  <div>
                    个人上下文：{" "}
                    {selectedChat.include_profile_context
                      ? "已启用"
                      : "已禁用"}
                  </div>
                  <div>
                    {" "}
                    工作区指令：{" "}
                    {selectedChat.include_workspace_instructions
                      ? "已启用"
                      : "已禁用"}
                  </div>

                  <div>
                    向量模型服务：{selectedChat.embeddings_provider}
                  </div>
                </div>
              </div>
            }
            trigger={
              <div className="mt-1">
                <IconInfoCircle
                  className="cursor-default hover:opacity-50"
                  size={24}
                />
              </div>
            }
          />

          <WithTooltip
            delayDuration={200}
            display={<div>开始新对话</div>}
            trigger={
              <div className="mt-1">
                <IconMessagePlus
                  className="cursor-pointer hover:opacity-50"
                  size={24}
                  onClick={handleNewChat}
                />
              </div>
            }
          />
        </>
      )}
    </>
  )
}
