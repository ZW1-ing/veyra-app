"use client"

import { AppearanceProvider } from "@/components/local/appearance-provider"
import {
  IconDatabase,
  IconMessage,
  IconSettings,
  IconUsers
} from "@tabler/icons-react"
import { cn } from "@/lib/utils"
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
    <div className="text-foreground flex h-dvh w-full">
      <AppearanceProvider />
      <nav className="veyra-panel bg-card border-border/70 flex w-[68px] shrink-0 flex-col items-center gap-1.5 border-r py-3">
        <div className="bg-primary text-primary-foreground mb-2 flex size-8 items-center justify-center rounded-md text-[13px] font-semibold shadow-[0_2px_6px_rgba(15,23,42,0.16)]">
          V
        </div>

        {NAV.map(item => {
          const active =
            item.href === "/local"
              ? pathname === "/local"
              : pathname.startsWith(item.href)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex w-14 flex-col items-center gap-1 rounded-md py-2 text-[11px] transition-colors",
                active
                  ? "bg-brand/10 text-brand ring-brand/10 font-medium ring-1 ring-inset"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              )}
            >
              <Icon size={18} stroke={1.75} />
              {item.label}
            </Link>
          )
        })}
      </nav>

      <div className="flex min-w-0 flex-1">{children}</div>
    </div>
  )
}
