"use client"

import { ChatbotUISVG } from "@/components/icons/chatbotui-svg"
import { supabaseConfigured } from "@/lib/supabase/browser-client"
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
        href={supabaseConfigured ? "/login" : "/local"}
      >
        {supabaseConfigured ? "开始对话" : "进入本地模式"}
        <IconArrowRight className="ml-1" size={20} />
      </Link>

      {!supabaseConfigured && (
        <p className="text-muted-foreground mt-4 max-w-md px-6 text-center text-sm leading-relaxed">
          未检测到 Supabase 配置，已按本地模式启动：不需要登录，会话存在这台浏览器里，
          由本机的 Python 后端负责检索与生成。工作区、文件、助手等功能仍需配置 Supabase。
        </p>
      )}
    </div>
  )
}
