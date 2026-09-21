import type { ReactNode } from 'react'

/** The base panel: a sheet of paper on a warm canvas. */
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
    <Tag className={`pg-card p-5 ${className}`} {...rest}>
      {children}
    </Tag>
  )
}
