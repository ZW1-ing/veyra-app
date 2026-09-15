import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/** 合并 Tailwind 类名：后写的覆盖先写的，冲突类不会叠在一起 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
