/**
 * Band presentation, tuned for a light surface.
 *
 * Band is never encoded by colour alone: every treatment pairs a colour with a
 * text label and a glyph, because this is a health-safety interface and a
 * colour-blind or monochrome reader must get the same information.
 *
 * Foreground colours are darkened relative to the dark theme so each clears
 * WCAG AA against paper; fills are the same hue at low alpha so the band reads
 * at a glance without the text losing contrast.
 */

export interface BandStyle {
  label: string
  short: string
  glyph: string
  fg: string
  bg: string
  border: string
  /** Solid colour for map fills and chart marks. */
  solid: string
  weight: 'low' | 'medium' | 'high' | 'critical'
}

const STYLES: Record<string, BandStyle> = {
  good: {
    label: 'Good',
    short: 'Good',
    glyph: '●',
    fg: '#2f6b4a',
    bg: 'rgba(47,107,74,0.10)',
    border: 'rgba(47,107,74,0.38)',
    solid: '#4f9a72',
    weight: 'low',
  },
  moderate: {
    label: 'Moderate',
    short: 'Mod',
    glyph: '◆',
    fg: '#7a5d10',
    bg: 'rgba(138,106,18,0.12)',
    border: 'rgba(138,106,18,0.38)',
    solid: '#d0a63a',
    weight: 'low',
  },
  unhealthy: {
    label: 'Unhealthy',
    short: 'Unhealthy',
    glyph: '▲',
    fg: '#a8490d',
    bg: 'rgba(180,83,15,0.14)',
    border: 'rgba(180,83,15,0.55)',
    solid: '#e07a2c',
    weight: 'medium',
  },
  very_unhealthy: {
    label: 'Very Unhealthy',
    short: 'V.Unhealthy',
    glyph: '▲▲',
    fg: '#8d2718',
    bg: 'rgba(155,44,26,0.16)',
    border: 'rgba(155,44,26,0.6)',
    solid: '#c04530',
    weight: 'high',
  },
  hazardous: {
    label: 'Hazardous',
    short: 'Hazardous',
    glyph: '■',
    fg: '#ffffff',
    bg: '#6d1a12',
    border: '#571009',
    solid: '#6d1a12',
    weight: 'critical',
  },
  normal: {
    label: 'Normal (Band 1)',
    short: 'Normal',
    glyph: '●',
    fg: '#2f6b4a',
    bg: 'rgba(47,107,74,0.10)',
    border: 'rgba(47,107,74,0.38)',
    solid: '#4f9a72',
    weight: 'low',
  },
  elevated: {
    label: 'Elevated (Band 2)',
    short: 'Elevated',
    glyph: '▲',
    fg: '#a8490d',
    bg: 'rgba(180,83,15,0.14)',
    border: 'rgba(180,83,15,0.55)',
    solid: '#e07a2c',
    weight: 'medium',
  },
  high: {
    label: 'High (Band 3)',
    short: 'High',
    glyph: '▲▲',
    fg: '#8d2718',
    bg: 'rgba(155,44,26,0.16)',
    border: 'rgba(155,44,26,0.6)',
    solid: '#c04530',
    weight: 'high',
  },
  very_high: {
    label: 'Very High (Band 4)',
    short: 'V.High',
    glyph: '■',
    fg: '#ffffff',
    bg: '#6d1a12',
    border: '#571009',
    solid: '#6d1a12',
    weight: 'critical',
  },
}

const UNKNOWN: BandStyle = {
  label: 'Unknown',
  short: '—',
  glyph: '—',
  fg: '#78756c',
  bg: 'rgba(120,117,108,0.10)',
  border: 'rgba(120,117,108,0.35)',
  solid: '#a8a49a',
  weight: 'low',
}

export function bandStyle(band?: string | null): BandStyle {
  if (!band) return UNKNOWN
  return STYLES[band] ?? UNKNOWN
}

/** Resolve a 24-hour PSI value to its band key. Mirrors app/agent/tools/bands.py. */
export function psiBandKey(psi: number | null | undefined): string | null {
  if (psi === null || psi === undefined || Number.isNaN(psi)) return null
  if (psi <= 50) return 'good'
  if (psi <= 100) return 'moderate'
  if (psi <= 200) return 'unhealthy'
  if (psi <= 300) return 'very_unhealthy'
  return 'hazardous'
}

export interface DecisionStyle {
  label: string
  glyph: string
  fg: string
  bg: string
  border: string
}

const DECISIONS: Record<string, DecisionStyle> = {
  proceed: {
    label: 'PROCEED',
    glyph: '✓',
    fg: '#2f6b4a',
    bg: 'rgba(47,107,74,0.10)',
    border: 'rgba(47,107,74,0.45)',
  },
  proceed_with_precautions: {
    label: 'PROCEED WITH PRECAUTIONS',
    glyph: '✓!',
    fg: '#7a5d10',
    bg: 'rgba(138,106,18,0.12)',
    border: 'rgba(138,106,18,0.45)',
  },
  restrict: {
    label: 'RESTRICT',
    glyph: '▲',
    fg: '#a8490d',
    bg: 'rgba(180,83,15,0.14)',
    border: 'rgba(180,83,15,0.6)',
  },
  suspend: {
    label: 'SUSPEND',
    glyph: '■',
    fg: '#8d2718',
    bg: 'rgba(155,44,26,0.16)',
    border: 'rgba(155,44,26,0.7)',
  },
  abstain: {
    label: 'NO GOVERNING GUIDANCE',
    glyph: '?',
    fg: '#2b5d8a',
    bg: 'rgba(43,93,138,0.10)',
    border: 'rgba(43,93,138,0.45)',
  },
}

export function decisionStyle(decision?: string | null): DecisionStyle {
  if (!decision) return DECISIONS.abstain
  return DECISIONS[decision] ?? DECISIONS.abstain
}

export function relativeAge(seconds: number): string {
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  return `${hours} h ago`
}
