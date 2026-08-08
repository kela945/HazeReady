export type Decision =
  | 'proceed'
  | 'proceed_with_precautions'
  | 'restrict'
  | 'suspend'
  | 'abstain'

export type RoleId =
  | 'general_public'
  | 'preschool'
  | 'school'
  | 'eldercare'
  | 'worksite'
  | 'event'

export interface BandResult {
  value: number
  index: 'psi_24h' | 'pm25_1h'
  band: string
  band_label: string
  lower_bound: number
  upper_bound: number | null
  boundary_note: string
  source_doc_id: string
}

export interface Reading {
  region: string
  psi_24h: number | null
  pm25_1h: number | null
  reading_timestamp: string
  fetched_at: string
  staleness_seconds: number
  source: 'live' | 'fixture'
  note: string
}

export interface Forecast {
  horizon_hours: number
  psi_low: number
  psi_high: number
  band_low: string
  band_high: string
  straddles_boundary: boolean
  source: string
  note: string
}

export interface Citation {
  marker: number
  doc_id: string
  chunk_id: string
  title: string
  issuing_agency: string
  source_url: string
  retrieved_at: string
  char_span: [number, number]
  authority_tier: 'primary' | 'secondary' | 'explanatory'
  quote: string
}

export interface ToolCall {
  hop: number
  tool: string
  arguments: Record<string, unknown>
  result_summary: string
  latency_ms: number
  ok: boolean
  error: string
}

export interface GuardrailEvent {
  guardrail: string
  triggered: boolean
  detail: string
  action: string
}

export interface Abstention {
  reason: string
  plain_language: string
  suggested_authority: string
  evidence_doc_id: string | null
  gap_id: string | null
}

export interface Advisory {
  query_id: string
  question: string
  role: RoleId
  role_routed_by: string
  router_confidence: number
  decision: Decision
  decision_label: string
  reason_codes: string[]
  obligations: string[]
  rationale: string
  citations: Citation[]
  band_result: BandResult | null
  reading: Reading | null
  forecast: Forecast | null
  hotspots: { count: number; source: string; note: string } | null
  abstention: Abstention | null
  conflicts: string[]
  trajectory: ToolCall[]
  guardrail_events: GuardrailEvent[]
  disclaimer: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  model: string
  provider: string
  top_retrieval_score: number
  llm_error: string
}

export interface Conditions {
  reading: Reading
  band: BandResult
  pm25_band: BandResult
  forecast: Forecast
  hotspots: { count: number; source: string; note: string }
  regions: Record<string, { psi_24h: number; pm25_1h: number; band: string }>
  offline_mode: boolean
  is_stale: boolean
}

export interface DocResponse {
  doc_id: string
  title: string
  issuing_agency: string
  source_url: string
  retrieved_at: string
  licence: string
  provenance: string
  verified_against_source: boolean
  authority_tier: string
  robots_txt_permits: boolean
  body: string
}
