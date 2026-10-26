import type { CSSOptions } from 'vite'

// The toolbar's Light and Dark for stories. A page can't set `prefers-color-scheme`, so every dark block is scoped to
// `<html data-theme="dark">`, the way reduceMotion.ts answers the app's Reduce Motion switch:
//
//   @media (prefers-color-scheme: dark) { .a { x } }   becomes   :where(:root[data-theme=dark]) .a { x }
type PostcssPlugin = NonNullable<Exclude<CSSOptions['postcss'], string | undefined>['plugins']>[number]
const DARK = /^\(\s*prefers-color-scheme\s*:\s*dark\s*\)$/i

function whenDark(selector: string): string {
  const root = /^(?::root|html)(?![\w-])/i.exec(selector)
  return root ? `${root[0]}:where([data-theme=dark])${selector.slice(root[0].length)}` : `:where(:root[data-theme=dark]) ${selector}`
}

export const colorSchemeRules: PostcssPlugin = {
  postcssPlugin: 'storybook-color-scheme',
  Once(root) {
    root.walkAtRules('media', (media) => {
      if (!DARK.test(media.params.trim())) return
      for (const node of media.nodes ?? []) {
        if (node.type === 'rule') node.selectors = node.selectors.map(whenDark)
      }
      media.replaceWith(media.nodes ?? [])
    })
  },
}
