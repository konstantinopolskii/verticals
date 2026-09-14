import './iridescent.css'

type FinishTier = 'webgl' | 'static' | 'flat'

interface CardEntry {
  element: HTMLElement
  visible: boolean
  seed: number
  hover: number
  tiltX: number
  tiltY: number
  rect: DOMRect | null
}

interface GlState {
  gl: WebGLRenderingContext
  extension: ANGLE_instanced_arrays
  program: WebGLProgram
  cornerBuffer: WebGLBuffer
  instanceBuffer: WebGLBuffer
  timeUniform: WebGLUniformLocation
  viewportUniform: WebGLUniformLocation
  intensityUniform: WebGLUniformLocation
  angleUniform: WebGLUniformLocation
  hueRangeUniform: WebGLUniformLocation
  speedUniform: WebGLUniformLocation
}

interface OverlayController {
  attach(entry: CardEntry): void
  detach(entry: CardEntry): void
  destroy(): void
}

const cards = new Map<HTMLElement, CardEntry>()
let activeOverlay: OverlayController | null = null

function seedFor(element: HTMLElement): number {
  const source = element.dataset.goalId ?? `${cards.size}`
  let hash = 2166136261
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return ((hash >>> 0) / 0xffffffff) * Math.PI * 2
}

function supportsBlendMode(): boolean {
  return typeof CSS !== 'undefined' && CSS.supports('mix-blend-mode', 'soft-light')
}

function fallbackTier(): FinishTier {
  return supportsBlendMode() ? 'static' : 'flat'
}

function applyTier(element: HTMLElement, tier: FinishTier): void {
  element.classList.toggle('foil--static', tier === 'static')
  element.classList.toggle('foil--flat', tier === 'flat')
}

export function registerIridescentCard(element: HTMLElement): void {
  element.dataset.foil = 'true'
  const existing = cards.get(element)
  if (existing) {
    // Re-registration doubles as tier repair: Vue rewrites the class attribute whenever a
    // card's bound classes change (a board refetch flipping data-colored is enough), wiping
    // the imperative foil--static/--flat mark. attach() re-applies the overlay's tier; with
    // no overlay yet, re-assert the fallback directly.
    if (activeOverlay) activeOverlay.attach(existing)
    else applyTier(element, fallbackTier())
    return
  }
  const entry: CardEntry = {
    element,
    visible: false,
    seed: seedFor(element),
    hover: 0,
    tiltX: 0,
    tiltY: 0,
    rect: null,
  }
  cards.set(element, entry)
  applyTier(element, fallbackTier())
  activeOverlay?.attach(entry)
}

export function unregisterIridescentCard(element: HTMLElement): void {
  const entry = cards.get(element)
  if (entry) activeOverlay?.detach(entry)
  cards.delete(element)
  element.classList.remove('foil--static', 'foil--flat')
  delete element.dataset.foil
}

function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader
  gl.deleteShader(shader)
  return null
}

const VERTEX_SHADER = `
attribute vec2 aCorner;
attribute vec4 aRect;
attribute float aSeed;
attribute float aHover;
attribute vec2 aTilt;
uniform vec2 uViewport;
varying vec2 vUv;
varying float vSeed;
varying float vHover;
varying vec2 vTilt;

void main() {
  vec2 pixel = aRect.xy + aCorner * aRect.zw;
  vec2 clip = pixel / uViewport * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  vUv = aCorner;
  vSeed = aSeed;
  vHover = aHover;
  vTilt = aTilt;
}
`

const FRAGMENT_SHADER = `
precision mediump float;
uniform float uTime;
uniform float uIntensity;
uniform float uAngle;
uniform float uHueRange;
uniform float uSpeed;
varying vec2 vUv;
varying float vSeed;
varying float vHover;
varying vec2 vTilt;

vec3 hslToRgb(float hue, float saturation, float lightness) {
  vec3 wave = abs(mod(hue * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0;
  vec3 rgb = clamp(wave, 0.0, 1.0);
  float chroma = (1.0 - abs(2.0 * lightness - 1.0)) * saturation;
  return (rgb - 0.5) * chroma + lightness;
}

void main() {
  // Technique port only: Balatro-style scalar phase and three-term polychrome field.
  // No copyrighted game shader source is included here.
  float tilt = vHover * dot(vTilt, vec2(0.16, -0.12));
  float phase = sin((uTime * uSpeed + vSeed) / 28.0) + 1.0 + tilt;
  float c = cos(uAngle);
  float s = sin(uAngle);
  vec2 centered = vUv - 0.5;
  vec2 p = mat2(c, -s, s, c) * centered;
  float field = (
    sin(p.x * 13.0 + phase * 2.1)
    + cos(p.y * 17.0 - phase * 1.6)
    + sin((p.x + p.y) * 21.0 + phase * 1.2)
  ) / 3.0;
  float hue = fract(0.58 + vSeed * 0.08 + field * uHueRange);
  float saturation = max(0.58, 0.55 + abs(field) * 0.22);
  vec3 color = hslToRgb(hue, saturation, 0.58);

  float edgeDistance = min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y));
  float edgeMask = 1.0 - smoothstep(0.015, 0.16, edgeDistance);
  vec2 hotspotCenter = 0.5 + vTilt * 0.24;
  float glare = vHover * (1.0 - smoothstep(0.05, 0.72, distance(vUv, hotspotCenter)));
  float mask = 0.18 + edgeMask * 0.62 + glare * 0.20;
  // soft-light canvas compositing supplies the underlying card-luminance gate: near-white body
  // stays quiet while borders and ink-adjacent contrast carry the hue.
  float alpha = uIntensity * mask * (0.07 + abs(field) * 0.07);
  gl_FragColor = vec4(color, alpha);
}
`

function requiredUniform(
  gl: WebGLRenderingContext,
  program: WebGLProgram,
  name: string,
): WebGLUniformLocation | null {
  return gl.getUniformLocation(program, name)
}

function createGlState(canvas: HTMLCanvasElement): GlState | null {
  const gl = canvas.getContext('webgl', {
    alpha: true,
    antialias: false,
    premultipliedAlpha: false,
  })
  if (!gl) return null
  const extension = gl.getExtension('ANGLE_instanced_arrays')
  if (!extension) return null
  const vertex = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER)
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER)
  if (!vertex || !fragment) return null
  const program = gl.createProgram()
  if (!program) return null
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  gl.deleteShader(vertex)
  gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program)
    return null
  }
  const cornerBuffer = gl.createBuffer()
  const instanceBuffer = gl.createBuffer()
  const timeUniform = requiredUniform(gl, program, 'uTime')
  const viewportUniform = requiredUniform(gl, program, 'uViewport')
  const intensityUniform = requiredUniform(gl, program, 'uIntensity')
  const angleUniform = requiredUniform(gl, program, 'uAngle')
  const hueRangeUniform = requiredUniform(gl, program, 'uHueRange')
  const speedUniform = requiredUniform(gl, program, 'uSpeed')
  if (
    !cornerBuffer || !instanceBuffer || !timeUniform || !viewportUniform
    || !intensityUniform || !angleUniform || !hueRangeUniform || !speedUniform
  ) return null

  gl.useProgram(program)
  gl.bindBuffer(gl.ARRAY_BUFFER, cornerBuffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW)
  const cornerLocation = gl.getAttribLocation(program, 'aCorner')
  gl.enableVertexAttribArray(cornerLocation)
  gl.vertexAttribPointer(cornerLocation, 2, gl.FLOAT, false, 0, 0)

  gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer)
  const stride = 8 * Float32Array.BYTES_PER_ELEMENT
  const attributes: Array<[string, number, number]> = [
    ['aRect', 4, 0],
    ['aSeed', 1, 4],
    ['aHover', 1, 5],
    ['aTilt', 2, 6],
  ]
  for (const [name, size, offset] of attributes) {
    const location = gl.getAttribLocation(program, name)
    gl.enableVertexAttribArray(location)
    gl.vertexAttribPointer(
      location,
      size,
      gl.FLOAT,
      false,
      stride,
      offset * Float32Array.BYTES_PER_ELEMENT,
    )
    extension.vertexAttribDivisorANGLE(location, 1)
  }
  gl.enable(gl.BLEND)
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
  gl.clearColor(0, 0, 0, 0)
  return {
    gl,
    extension,
    program,
    cornerBuffer,
    instanceBuffer,
    timeUniform,
    viewportUniform,
    intensityUniform,
    angleUniform,
    hueRangeUniform,
    speedUniform,
  }
}

function numericProperty(style: CSSStyleDeclaration, name: string, fallback: number): number {
  const parsed = Number.parseFloat(style.getPropertyValue(name))
  return Number.isFinite(parsed) ? parsed : fallback
}

function angleProperty(style: CSSStyleDeclaration): number {
  const raw = style.getPropertyValue('--iridescence-angle').trim()
  const parsed = Number.parseFloat(raw)
  if (!Number.isFinite(parsed)) return (125 * Math.PI) / 180
  if (raw.endsWith('turn')) return parsed * Math.PI * 2
  if (raw.endsWith('rad')) return parsed
  return (parsed * Math.PI) / 180
}

export function mountIridescentOverlay(
  boardRoot: HTMLElement,
  canvas: HTMLCanvasElement,
): () => void {
  activeOverlay?.destroy()
  const observed = new Set<CardEntry>()
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const blendMode = supportsBlendMode()
  let tier: FinishTier = !blendMode || reducedMotion ? (blendMode ? 'static' : 'flat') : 'webgl'
  let glState = tier === 'webgl' ? createGlState(canvas) : null
  if (tier === 'webgl' && !glState) tier = fallbackTier()
  canvas.dataset.tier = tier
  canvas.hidden = true

  const style = getComputedStyle(canvas)
  const config = {
    intensity: numericProperty(style, '--iridescence-intensity', 0.55),
    angle: angleProperty(style),
    hueRange: numericProperty(style, '--iridescence-hue-range', 0.16),
    speed: numericProperty(style, '--iridescence-speed', 1),
  }
  let animationFrame: number | null = null
  let rectsDirty = true
  let lastDraw = 0
  let hovered: CardEntry | null = null

  const visibleEntries = (): CardEntry[] => [...observed].filter((entry) => entry.visible)

  function intersectsViewport(rect: DOMRect): boolean {
    return rect.width > 0
      && rect.height > 0
      && rect.right > 0
      && rect.bottom > 0
      && rect.left < window.innerWidth
      && rect.top < window.innerHeight
  }

  function stopLoop(): void {
    if (animationFrame !== null) cancelAnimationFrame(animationFrame)
    animationFrame = null
    canvas.hidden = true
  }

  function ensureLoop(): void {
    if (tier !== 'webgl' || document.hidden || visibleEntries().length === 0) {
      stopLoop()
      return
    }
    canvas.hidden = false
    if (animationFrame === null) animationFrame = requestAnimationFrame(draw)
  }

  function markRectsDirty(): void {
    rectsDirty = true
    ensureLoop()
  }

  const resizeObserver = new ResizeObserver(markRectsDirty)
  const intersectionObserver = new IntersectionObserver((records) => {
    for (const record of records) {
      const entry = cards.get(record.target as HTMLElement)
      if (!entry || !observed.has(entry)) continue
      entry.visible = record.isIntersecting && record.intersectionRatio > 0
      if (!entry.visible) entry.rect = null
    }
    rectsDirty = true
    ensureLoop()
  })

  function attach(entry: CardEntry): void {
    if (!boardRoot.contains(entry.element)) {
      applyTier(entry.element, fallbackTier())
      return
    }
    applyTier(entry.element, tier)
    if (observed.has(entry)) return
    observed.add(entry)
    entry.visible = intersectsViewport(entry.element.getBoundingClientRect())
    resizeObserver.observe(entry.element)
    intersectionObserver.observe(entry.element)
    rectsDirty = true
    ensureLoop()
  }

  function detach(entry: CardEntry): void {
    if (!observed.delete(entry)) return
    resizeObserver.unobserve(entry.element)
    intersectionObserver.unobserve(entry.element)
    entry.visible = false
    entry.rect = null
    if (hovered === entry) hovered = null
    ensureLoop()
  }

  function updateCanvasAndRects(): CardEntry[] {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const width = Math.max(1, Math.round(viewportWidth * dpr))
    const height = Math.max(1, Math.round(viewportHeight * dpr))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    canvas.style.left = '0px'
    canvas.style.top = '0px'
    canvas.style.width = `${viewportWidth}px`
    canvas.style.height = `${viewportHeight}px`
    const drawable: CardEntry[] = []
    for (const entry of visibleEntries()) {
      const rect = entry.element.getBoundingClientRect()
      entry.rect = rect
      if (rect.width > 0 && rect.height > 0) drawable.push(entry)
    }
    rectsDirty = false
    return drawable
  }

  function draw(timestamp: number): void {
    animationFrame = null
    if (tier !== 'webgl' || document.hidden || !glState) {
      stopLoop()
      return
    }
    const hasHover = hovered !== null
    if (!hasHover && timestamp - lastDraw < 1000 / 15 && !rectsDirty) {
      animationFrame = requestAnimationFrame(draw)
      return
    }
    const drawable = updateCanvasAndRects()
    if (drawable.length === 0) {
      stopLoop()
      return
    }
    lastDraw = timestamp
    const instanceData = new Float32Array(drawable.length * 8)
    drawable.forEach((entry, index) => {
      const rect = entry.rect as DOMRect
      instanceData.set([
        rect.left,
        rect.top,
        rect.width,
        rect.height,
        entry.seed,
        entry.hover,
        entry.tiltX,
        entry.tiltY,
      ], index * 8)
    })
    const { gl, extension, instanceBuffer, program } = glState
    gl.viewport(0, 0, canvas.width, canvas.height)
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.useProgram(program)
    gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, instanceData, gl.DYNAMIC_DRAW)
    gl.uniform1f(glState.timeUniform, timestamp / 1000)
    gl.uniform2f(glState.viewportUniform, window.innerWidth, window.innerHeight)
    gl.uniform1f(glState.intensityUniform, config.intensity)
    gl.uniform1f(glState.angleUniform, config.angle)
    gl.uniform1f(glState.hueRangeUniform, config.hueRange)
    gl.uniform1f(glState.speedUniform, config.speed)
    extension.drawArraysInstancedANGLE(gl.TRIANGLE_STRIP, 0, 4, drawable.length)
    animationFrame = requestAnimationFrame(draw)
  }

  function clearHover(): void {
    if (!hovered) return
    hovered.hover = 0
    hovered.tiltX = 0
    hovered.tiltY = 0
    hovered = null
  }

  function onPointerMove(event: PointerEvent): void {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('.foil') : null
    const entry = target ? cards.get(target) : undefined
    if (!entry || !observed.has(entry)) {
      clearHover()
      return
    }
    if (hovered && hovered !== entry) {
      hovered.hover = 0
      hovered.tiltX = 0
      hovered.tiltY = 0
    }
    const rect = entry.element.getBoundingClientRect()
    entry.hover = 1
    entry.tiltX = ((event.clientX - rect.left) / rect.width) * 2 - 1
    entry.tiltY = ((event.clientY - rect.top) / rect.height) * 2 - 1
    hovered = entry
    ensureLoop()
  }

  function onVisibilityChange(): void {
    if (document.hidden) stopLoop()
    else ensureLoop()
  }

  function degradeAfterContextLoss(event: Event): void {
    event.preventDefault()
    tier = fallbackTier()
    glState = null
    canvas.dataset.tier = tier
    stopLoop()
    for (const entry of observed) applyTier(entry.element, tier)
  }

  boardRoot.addEventListener('pointermove', onPointerMove)
  boardRoot.addEventListener('pointerleave', clearHover)
  boardRoot.addEventListener('scroll', markRectsDirty, true)
  window.addEventListener('resize', markRectsDirty)
  document.addEventListener('visibilitychange', onVisibilityChange)
  canvas.addEventListener('webglcontextlost', degradeAfterContextLoss)

  const controller: OverlayController = {
    attach,
    detach,
    destroy(): void {
      stopLoop()
      boardRoot.removeEventListener('pointermove', onPointerMove)
      boardRoot.removeEventListener('pointerleave', clearHover)
      boardRoot.removeEventListener('scroll', markRectsDirty, true)
      window.removeEventListener('resize', markRectsDirty)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      canvas.removeEventListener('webglcontextlost', degradeAfterContextLoss)
      resizeObserver.disconnect()
      intersectionObserver.disconnect()
      for (const entry of observed) {
        entry.visible = false
        entry.rect = null
        applyTier(entry.element, fallbackTier())
      }
      observed.clear()
      canvas.hidden = true
      if (activeOverlay === controller) activeOverlay = null
    },
  }
  activeOverlay = controller
  for (const entry of cards.values()) attach(entry)
  ensureLoop()
  return () => controller.destroy()
}
