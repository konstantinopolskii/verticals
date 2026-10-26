import type { Preview } from '@storybook/react-vite'
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import '../src/tokens.css'
import '../src/base.css'
import './preview.css'

const preview: Preview = {
  parameters: { layout: 'padded' },
  initialGlobals: { theme: 'light' },
  globalTypes: {
    theme: {
      description: 'Appearance',
      toolbar: { icon: 'mirror', items: [{ value: 'light', title: 'Light' }, { value: 'dark', title: 'Dark' }], dynamicTitle: true },
    },
  },
  decorators: [
    (Story, { globals }) => {
      document.documentElement.dataset.theme = globals.theme === 'dark' ? 'dark' : 'light'
      return Story()
    },
  ],
}

export default preview
