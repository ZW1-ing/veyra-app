import { ChatbotUIContext } from "@/context/context"
import { IconAdjustmentsHorizontal } from "@tabler/icons-react"
import { FC, useContext, useState } from "react"
import { Button } from "../ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTrigger
} from "../ui/dialog"
import { Label } from "../ui/label"
import { Slider } from "../ui/slider"
import { WithTooltip } from "../ui/with-tooltip"

interface ChatRetrievalSettingsProps {}

export const ChatRetrievalSettings: FC<ChatRetrievalSettingsProps> = ({}) => {
  const { sourceCount, setSourceCount } = useContext(ChatbotUIContext)

  const [isOpen, setIsOpen] = useState(false)

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger>
        <WithTooltip
          delayDuration={0}
          side="top"
          display={<div>调整知识检索设置。</div>}
          trigger={
            <IconAdjustmentsHorizontal
              className="cursor-pointer pt-[4px] hover:opacity-50"
              size={24}
            />
          }
        />
      </DialogTrigger>

      <DialogContent>
        <div className="space-y-3">
          <Label className="flex items-center space-x-1">
            <div>来源数量：</div>

            <div>{sourceCount}</div>
          </Label>

          <Slider
            value={[sourceCount]}
            onValueChange={values => {
              setSourceCount(values[0])
            }}
            min={1}
            max={10}
            step={1}
          />
        </div>

        <DialogFooter>
          <Button size="sm" onClick={() => setIsOpen(false)}>
            保存并关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
