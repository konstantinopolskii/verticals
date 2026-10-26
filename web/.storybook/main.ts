import type { StorybookConfig } from '@storybook/react-vite'
import { colorSchemeRules } from './colorScheme'

const config: StorybookConfig = {
  framework: '@storybook/react-vite',
  stories: ['../src/**/*.stories.tsx'],
  core: { disableTelemetry: true },
  viteFinal(config) {
    const postcss = config.css?.postcss
    if (postcss && typeof postcss === 'object') postcss.plugins = [...(postcss.plugins ?? []), colorSchemeRules]
    return config
  },
}

export default config
