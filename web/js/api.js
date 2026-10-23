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
const task = v => object(v) && uuid(v.id) && uuid(v.entity_id) && v.kind === 'source_refresh'
  && v.entity_type === 'source_board' && statuses.includes(v.status)
  && text(v.current_step) && number(v.progress) && v.progress <= 100 && number(v.attempts) && number(v.max_attempts)
  && nullableTime(v.retry_at) && timestamp(v.created_at) && timestamp(v.updated_at) && nullableTime(v.finished_at)
  && nullableText(v.error_code) && (v.result === null || (object(v.result) && number(v.result.listing_count)
    && ['live', 'fixture'].includes(v.result.data_origin))) && (v.status !== 'SUCCEEDED' || v.result !== null);
const validators = {
  session: v => object(v) && typeof v.connected === 'boolean',
  health: v => object(v) && text(v.version) && typeof v.api_ready === 'boolean' && typeof v.database_ready === 'boolean'
    && object(v.worker) && typeof v.worker.ready === 'boolean',
  boards: v => Array.isArray(v) && v.every(board),
  jobs: v => object(v) && Array.isArray(v.items) && v.items.every(job) && number(v.total) && number(v.offset)
    && number(v.limit) && v.limit > 0 && v.items.length <= v.limit && nullableTime(v.last_refreshed_at),
  reference: v => object(v) && uuid(v.task_id) && uuid(v.entity_id) && v.entity_type === 'source_board',
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
  try {
    const response = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: {'Accept': 'application/json', 'X-CareerLens-Local': '1',
        ...(method !== 'GET' ? {'Content-Type': 'application/json'} : {}),
        ...(key ? {'Idempotency-Key': key} : {})},
      ...(body !== undefined ? {body: JSON.stringify(body)} : {}),
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
