import type { ReactNode } from 'react'

/** Frosted-glass surface — the base panel of the aurora system (spec 00 A2). */
export function Card({
  children,
  className = '',
  as: Tag = 'div',
  ...rest
}: {
  children: ReactNode
  className?: string
  as?: 'div' | 'section' | 'article' | 'aside'
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag className={`aurora-glass p-5 ${className}`} {...rest}>
      {children}
    </Tag>
  )
}
