/*
 * Design controls are useful in local review builds, but production must render the
 * committed defaults. Set VITE_ENABLE_DEV_TUNING=0 for the production bundle: the
 * backslash shortcut disappears and browser-local experiments are ignored.
 */
export const DEV_TUNING_ENABLED = import.meta.env.VITE_ENABLE_DEV_TUNING !== '0'
