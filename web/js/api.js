export class ApiError extends Error {
  constructor(code, status = 0) { super(code); this.code = code; this.status = status; }
}

export const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string';
const number = value => Number.isInteger(value) && value >= 0;
const nullableText = value => value === null || text(value);
const timestamp = value => text(value) && Number.isFinite(Date.parse(value));
const nullableTime = value => value === null || timestamp(value);
export const statuses = ['QUEUED', 'RUNNING', 'WAITING', 'SUCCEEDED', 'FAILED', 'CANCELLED'];
export const terminal = task => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(task.status);

const board = v => object(v) && uuid(v.id) && text(v.employer) && text(v.family) && text(v.slug)
  && typeof v.enabled === 'boolean' && number(v.revision) && nullableTime(v.refreshed_at) && nullableText(v.last_error_code);
const job = v => object(v) && uuid(v.id) && text(v.title) && text(v.employer) && nullableText(v.location)
  && nullableText(v.employment_type) && text(v.source_url) && text(v.apply_url) && timestamp(v.fetched_at)
  && text(v.canonical_job_key) && text(v.external_id) && text(v.content_hash);
const taskTypes = {source_refresh:'source_board',resume_parse:'resume_upload',job_search:'search',jd_analysis:'job_analysis',resume_generate:'resume_generation'};
const taskResult = v => object(v) && uuid(v.entity_id) && ({
  source_board: () => number(v.listing_count) && ['live','fixture'].includes(v.data_origin),
  resume_upload: () => uuid(v.profile_version_id),
  search: () => ['NEEDS_ROLE_DECISION','COMPLETED'].includes(v.state) && number(v.result_count),
  job_analysis: () => true,
  resume_generation: () => uuid(v.resume_version_id) && uuid(v.artifact_id),
}[v.entity_type]?.() || false);
const reference = v => object(v) && uuid(v.task_id) && uuid(v.entity_id) && Object.values(taskTypes).includes(v.entity_type);
const task = v => object(v) && uuid(v.id) && uuid(v.entity_id) && taskTypes[v.kind] === v.entity_type && statuses.includes(v.status)
  && text(v.current_step) && number(v.progress) && v.progress <= 100 && number(v.attempts) && number(v.max_attempts)
  && nullableTime(v.retry_at) && timestamp(v.created_at) && timestamp(v.updated_at) && nullableTime(v.finished_at)
  && nullableText(v.error_code) && (v.result === null || (taskResult(v.result) && v.result.entity_type === v.entity_type))
  && (v.status !== 'SUCCEEDED' || v.result !== null);
const profileSummary = v => object(v) && uuid(v.id) && number(v.version) && number(v.revision) && nullableTime(v.confirmed_at)
  && (v.source_artifact_id === null || uuid(v.source_artifact_id));
const fact = v => object(v) && uuid(v.id) && uuid(v.stable_id) && text(v.kind) && text(v.text)
  && ['extracted','user'].includes(v.provenance) && (v.source_ref === null || (object(v.source_ref) && number(v.source_ref.page)
    && number(v.source_ref.start_offset) && number(v.source_ref.end_offset) && text(v.source_ref.source_text)));
const assessment = v => object(v) && (v.coverage === null || (typeof v.coverage === 'number' && v.coverage >= 0 && v.coverage <= 100))
  && ['required','preferred'].every(k => Array.isArray(v[k]) && v[k].every(s => object(s) && text(s.skill)
    && ['supported','not_evidenced'].includes(s.status) && Array.isArray(s.source_fact_ids) && s.source_fact_ids.every(uuid) && Array.isArray(s.evidence_kinds)))
  && Array.isArray(v.eligibility) && v.eligibility.every(text) && text(v.scope);
const jdSpan = v => object(v) && v.page === null && number(v.start_offset) && number(v.end_offset) && v.end_offset > v.start_offset && text(v.source_text);
const jdSkill = v => object(v) && text(v.canonical_name) && text(v.verbatim_text) && jdSpan(v.source_span);
const jdStatement = v => object(v) && text(v.text) && jdSpan(v.source_span);
const search = v => object(v) && uuid(v.id) && uuid(v.profile_version_id) && text(v.title) && text(v.original_title)
  && ['RUNNING','NEEDS_ROLE_DECISION','COMPLETED','FAILED'].includes(v.state) && number(v.revision)
  && Array.isArray(v.results) && v.results.length <= 5 && v.results.every(j => job(j) && text(j.match_explanation));
const generationSummary = v => object(v) && uuid(v.id) && uuid(v.profile_version_id) && uuid(v.analysis_id) && uuid(v.task_id)
  && ['QUEUED','RUNNING','VERIFIED','BLOCKED','FAILED'].includes(v.state) && nullableText(v.error_code);
const validators = {
  session: v => object(v) && typeof v.connected === 'boolean',
  health: v => object(v) && text(v.version) && typeof v.api_ready === 'boolean' && typeof v.database_ready === 'boolean'
    && object(v.worker) && typeof v.worker.ready === 'boolean',
  boards: v => Array.isArray(v) && v.every(board),
  jobs: v => object(v) && Array.isArray(v.items) && v.items.every(job) && number(v.total) && number(v.offset)
    && number(v.limit) && v.limit > 0 && v.items.length <= v.limit && nullableTime(v.last_refreshed_at),
  reference,
  references: v => Array.isArray(v) && v.every(reference),
  profiles: v => Array.isArray(v) && v.every(profileSummary),
  profile: v => profileSummary(v) && Array.isArray(v.facts) && v.facts.every(fact) && Array.isArray(v.pages)
    && v.pages.every(p => object(p) && number(p.page) && text(p.text)) && Array.isArray(v.warnings) && v.warnings.every(text)
    && object(v.parsing) && ['local','groq','local_fallback'].includes(v.parsing.mode)
    && ['local','groq'].includes(v.parsing.requested_mode),
  search,
  searches: v => Array.isArray(v) && v.every(search),
  analysis: v => object(v) && uuid(v.id) && uuid(v.profile_version_id) && uuid(v.job_snapshot_id) && text(v.job_title)
    && uuid(v.search_id) && text(v.employer) && text(v.raw_text) && text(v.content_hash) && object(v.structured)
    && ['required_skills','preferred_skills'].every(k => Array.isArray(v.structured[k]) && v.structured[k].every(jdSkill))
    && ['responsibilities','eligibility'].every(k => Array.isArray(v.structured[k]) && v.structured[k].every(jdStatement))
    && Array.isArray(v.structured.uncertainties) && v.structured.uncertainties.every(text) && assessment(v.assessment),
  generations: v => Array.isArray(v) && v.every(generationSummary),
  generation: v => generationSummary(v) && text(v.job_title) && text(v.employer)
    && (v.original_artifact_id === null || uuid(v.original_artifact_id))
    && (v.pdf_artifact_id === null || uuid(v.pdf_artifact_id)) && (v.content === null || (object(v.content)
      && object(v.content.tailored) && Array.isArray(v.content.tailored.changes) && v.content.tailored.changes.every(c => text(c.item_id) && text(c.before) && text(c.after) && text(c.reason))
      && Array.isArray(v.content.reverted_item_ids) && assessment(v.content.original_assessment) && assessment(v.content.tailored_assessment)
      && object(v.content.pdf_checks) && number(v.content.pdf_checks.pages) && ['groq','controlled_fixture'].includes(v.content.provider)
      && object(v.content.verification) && typeof v.content.verification.pass === 'boolean')),
  task,
  events: v => Array.isArray(v) && v.every(e => object(e) && uuid(e.id) && text(e.kind) && timestamp(e.created_at)),
};

// One request layer, no credentials in JavaScript and no automatic mutation retries.
export async function request(path, {method = 'GET', body, key, validate, signal} = {}) {
  if (!path.startsWith('/') || path.startsWith('//')) throw new ApiError('INVALID_DESTINATION');
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, {once: true});
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 10000);
  const multipart = body instanceof FormData;
  try {
    const response = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: {'Accept': 'application/json', 'X-CareerLens-Local': '1',
        ...(method !== 'GET' && !multipart ? {'Content-Type': 'application/json'} : {}),
        ...(key ? {'Idempotency-Key': key} : {})},
      ...(body !== undefined ? {body: multipart ? body : JSON.stringify(body)} : {}),
    });
    let value;
    try { value = await response.json(); }
    catch { throw new ApiError('INVALID_RESPONSE', response.status); }
    if (!response.ok) {
      const code = object(value.error) && text(value.error.code) ? value.error.code : 'REQUEST_FAILED';
      throw new ApiError(code, response.status);
    }
    if (!validators[validate]?.(value)) throw new ApiError('INVALID_RESPONSE', response.status);
    return value;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw new ApiError('CANCELLED_REQUEST');
    throw new ApiError(controller.signal.aborted ? 'TIMEOUT' : 'NETWORK');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export function explanation(error) {
  if (error.status === 401) return 'Your local session needs reconnecting. Select Connect to continue.';
  if (error.status === 403) return 'This request was blocked by the local security boundary. Open the same local address directly and reconnect.';
  if (error.status === 409) return 'The source changed or this request conflicts with an earlier action. Reload the source before trying again.';
  if (error.status === 404) return 'That record was not found in your local workspace. Check its ID.';
  if (error.code === 'INVALID_RESPONSE') return 'The backend returned an incomplete response. Previously loaded data is kept. Try again.';
  if (error.status >= 500) return 'The local backend could not complete this request. Check the development terminal and try again.';
  if (error.code === 'TIMEOUT') return 'The backend took too long to respond. Check that CareerLens is still running.';
  if (error.code === 'NETWORK') return 'Cannot reach the local backend. Start CareerLens, then try again.';
  return 'The request could not be completed. Check the local backend and try again.';
}
