import { ContentType } from "@/types"
import { CONTENT_TYPE_ZH } from "@/lib/ui-zh"
import { FC } from "react"
import { Input } from "../ui/input"

interface SidebarSearchProps {
  contentType: ContentType
  searchTerm: string
  setSearchTerm: Function
}

export const SidebarSearch: FC<SidebarSearchProps> = ({
  contentType,
  searchTerm,
  setSearchTerm
}) => {
  return (
    <Input
      placeholder={`搜索${CONTENT_TYPE_ZH[contentType]}...`}
      value={searchTerm}
      onChange={e => setSearchTerm(e.target.value)}
    />
  )
}
