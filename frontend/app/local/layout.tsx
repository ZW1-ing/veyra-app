"use client"

import { IconDatabase, IconMessage, IconSettings, IconUsers } from "@tabler/icons-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ReactNode } from "react"

const NAV = [
  { href: "/local", label: "会话", icon: IconMessage },
  { href: "/local/assistants", label: "助手", icon: IconUsers },
  { href: "/local/kb", label: "知识库", icon: IconDatabase },
  { href: "/local/settings", label: "设置", icon: IconSettings }
]

/** 本地模式的应用外壳：左侧一条窄导航，右侧是各页面自己的内容 */
export default function LocalLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()

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
      </nav>

      <div className="flex min-w-0 flex-1">{children}</div>
    </div>
  )
}
