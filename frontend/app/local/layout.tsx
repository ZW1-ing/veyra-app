"use client"

import {
  IconChartBar,
  IconDatabase,
  IconMessage,
  IconMoon,
  IconSettings,
  IconSun,
  IconUsers
} from "@tabler/icons-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useTheme } from "next-themes"
import { ReactNode, useEffect, useState } from "react"

const NAV = [
  { href: "/local", label: "会话", icon: IconMessage },
  { href: "/local/assistants", label: "助手", icon: IconUsers },
  { href: "/local/kb", label: "知识库", icon: IconDatabase },
  { href: "/local/usage", label: "用量", icon: IconChartBar },
  { href: "/local/settings", label: "设置", icon: IconSettings }
]

/** 本地模式的应用外壳：左侧一条窄导航，右侧是各页面自己的内容 */
export default function LocalLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const { resolvedTheme, setTheme } = useTheme()
  // 服务端不知道当前主题，首帧必须与客户端保持一致：挂载前只渲染占位。
  // 否则图标会在水合时从「太阳」变成「月亮」，React 会报 hydration mismatch。
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  return (
    <div className="bg-background text-foreground flex h-dvh w-full">
      <nav className="flex w-16 shrink-0 flex-col items-center gap-1 border-r py-3">
        {NAV.map((item) => {
          const active =
            item.href === "/local" ? pathname === "/local" : pathname.startsWith(item.href)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={`flex w-12 flex-col items-center gap-0.5 rounded-md py-2 text-[11px] ${
                active ? "bg-accent" : "hover:bg-accent/50"
              }`}
            >
              <Icon size={18} />
              {item.label}
            </Link>
          )
        })}

        {/* 主题切换：钉在导航底部 */}
        <button
          className="hover:bg-accent mt-auto flex w-12 flex-col items-center gap-0.5 rounded-md py-2 text-[11px]"
          title={mounted ? (resolvedTheme === "dark" ? "切到亮色" : "切到暗色") : "主题"}
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          disabled={!mounted}
        >
          {/* 未挂载时渲染一个占位图标，避免首帧图标与客户端不一致 */}
          {!mounted ? (
            <span className="size-[18px]" />
          ) : resolvedTheme === "dark" ? (
            <IconSun size={18} />
          ) : (
            <IconMoon size={18} />
          )}
          主题
        </button>
      </nav>

      <div className="flex min-w-0 flex-1">{children}</div>
    </div>
  )
}
