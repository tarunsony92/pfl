'use client'

import {
  ToastProvider,
  ToastViewport,
  ToastRoot,
  ToastTitle,
  ToastDescription,
} from './toast'
import { useToast } from './use-toast'

export function Toaster() {
  const { toasts } = useToast()
  return (
    <ToastProvider>
      {toasts.map(({ id, title, description, variant }) => (
        <ToastRoot key={id} variant={variant}>
          <div className="flex-1">
            {title && <ToastTitle>{title}</ToastTitle>}
            {description && <ToastDescription>{description}</ToastDescription>}
          </div>
        </ToastRoot>
      ))}
      <ToastViewport />
    </ToastProvider>
  )
}
