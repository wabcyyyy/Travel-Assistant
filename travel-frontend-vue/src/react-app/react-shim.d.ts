/**
 * The repository already carries React runtime packages for the migration,
 * but its dependency lock predates the React type packages. Keep the
 * migration buildable offline with a small local declaration until the
 * workspace dependency refresh can add @types/react formally.
 */
declare module 'react' {
  export type ReactNode = any
  export type FormEvent<T = HTMLFormElement> = { preventDefault: () => void; currentTarget: T }
  export function useState<T = any>(initial?: T | (() => T)): [T, (value: any) => void]
  export function useEffect(effect: () => void | (() => void), dependencies?: unknown[]): void
  export function useMemo<T>(factory: () => T, dependencies: unknown[]): T
  export function useCallback<T extends (...args: any[]) => any>(callback: T, dependencies: unknown[]): T
  export function useRef<T>(initial: T): { current: T }
}

declare module 'react/jsx-runtime' {
  export const Fragment: unknown
  export function jsx(...args: any[]): any
  export function jsxs(...args: any[]): any
}

declare module 'react-dom/client' {
  export function createRoot(element: Element | DocumentFragment): { render(node: any): void }
}

// React 树测试（vitest）用静态渲染断言文案，不引新的测试依赖。
declare module 'react-dom/server' {
  export function renderToStaticMarkup(node: any): string
}

declare namespace JSX {
  interface IntrinsicElements {
    [elementName: string]: any
  }
}
