"use client"

import { ChatbotUISVG } from "@/components/icons/chatbotui-svg"
import { IconArrowRight } from "@tabler/icons-react"
import { useTheme } from "next-themes"
import Link from "next/link"

export default function HomePage() {
  const { theme } = useTheme()

  return (
    <div className="flex size-full flex-col items-center justify-center">
      <div>
        <ChatbotUISVG theme={theme === "dark" ? "dark" : "light"} scale={0.3} />
      </div>

      <div className="mt-2 text-4xl font-bold">智能对话</div>

      <Link
        className="mt-4 flex w-[200px] items-center justify-center rounded-md bg-blue-500 p-2 font-semibold"
        href="/local"
      >
        进入本地模式
        <IconArrowRight className="ml-1" size={20} />
      </Link>

      <p className="text-muted-foreground mt-4 max-w-md px-6 text-center text-sm leading-relaxed">
        不需要登录，会话存在这台浏览器里；检索、工具调用与多智能体由本机的 Python 后端执行。
      </p>
    </div>
  )
}
