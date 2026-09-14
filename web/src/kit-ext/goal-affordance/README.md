# Goal affordance

Top-right completion control for goal cards. Leaves use a square; containers use a milestone ring filled by descendant completion.

## API

`kind: 'square' | 'ring'`, `checked`, `done`, `total`, `color`; emits `toggle(boolean)`.

## Tokens

Uses `--space-1`, `--space-3`, `--space-4`, `--space-5`, `--radius-full`, `--color-bg`, `--color-border`, `--color-border-strong`, `--goal-ink`, `--dur-base`, `--ease-out`, and `--ease-quart`. Value colour enters only through `--goal-affordance-color`.
