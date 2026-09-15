import { Database } from "@/supabase/types"
import { createBrowserClient } from "@supabase/ssr"

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

/** 有没有配 Supabase。没配就是本地模式（只走自建 Python 后端）。 */
export const supabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey)

/**
 * 注意这里**不能**在模块加载时直接 createBrowserClient：
 * 这个模块被 db/ 下的数据访问层间接引入到几乎所有页面，缺环境变量时
 * 会在导入阶段就抛异常，表现为整页白屏（连不需要登录的页面也打不开）。
 * 所以没配置时返回一个「用到才报错」的代理，把问题推迟到真正调用处。
 */
export const supabase: ReturnType<typeof createBrowserClient<Database>> = supabaseConfigured
  ? createBrowserClient<Database>(supabaseUrl!, supabaseAnonKey!)
  : (new Proxy(
      {},
      {
        get() {
          throw new Error(
            "本地模式未配置 Supabase：这个功能依赖 Supabase，请在 frontend/.env.local 里填 NEXT_PUBLIC_SUPABASE_URL 与 NEXT_PUBLIC_SUPABASE_ANON_KEY"
          )
        }
      }
    ) as ReturnType<typeof createBrowserClient<Database>>)
