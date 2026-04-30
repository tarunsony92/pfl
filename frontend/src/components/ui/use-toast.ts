'use client'

import * as React from 'react'

type ToastVariant = 'default' | 'destructive'

export interface Toast {
  id: string
  title?: string
  description?: string
  variant?: ToastVariant
  duration?: number
}

type ToastInput = Omit<Toast, 'id'>

type ToastState = {
  toasts: Toast[]
}

type ToastAction =
  | { type: 'ADD'; toast: Toast }
  | { type: 'DISMISS'; id: string }

function reducer(state: ToastState, action: ToastAction): ToastState {
  switch (action.type) {
    case 'ADD':
      return { toasts: [...state.toasts, action.toast] }
    case 'DISMISS':
      return { toasts: state.toasts.filter((t) => t.id !== action.id) }
    default:
      return state
  }
}

const listeners: Array<(state: ToastState) => void> = []
let memoryState: ToastState = { toasts: [] }

function dispatch(action: ToastAction) {
  memoryState = reducer(memoryState, action)
  listeners.forEach((l) => l(memoryState))
}

function toast(input: ToastInput) {
  const id = Math.random().toString(36).slice(2)
  dispatch({ type: 'ADD', toast: { id, duration: 4000, ...input } })
  setTimeout(() => dispatch({ type: 'DISMISS', id }), input.duration ?? 4000)
}

function useToast() {
  const [state, setState] = React.useState<ToastState>(memoryState)
  React.useEffect(() => {
    listeners.push(setState)
    return () => {
      const idx = listeners.indexOf(setState)
      if (idx > -1) listeners.splice(idx, 1)
    }
  }, [])
  return { toasts: state.toasts, toast, dismiss: (id: string) => dispatch({ type: 'DISMISS', id }) }
}

export { useToast, toast }
