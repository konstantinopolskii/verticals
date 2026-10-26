import type { Preview } from '@storybook/react-vite'
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import '../src/tokens.css'
import '../src/base.css'
import './preview.css'

const preview: Preview = {
  parameters: { layout: 'padded' },
}

export default preview
