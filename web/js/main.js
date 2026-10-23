import {request, explanation, uuid, terminal} from './api.js';
import {$, node, words} from './dom.js';
import {renderHealth, renderSource, renderJobs, updateFilterOptions, showJob, renderTasks} from './views.js';
import {createStudio} from './studio.js';

const state = {
  connected: false, connecting: false, health: null, boards: [], boardId: null,
  jobs: [], total: null, lastRefreshed: null, jobsLoading: false, jobsError: null, stale: false,
  tasks: new Map(), events: new Map(), selectedTask: null, command: null, sending: false,
};
const polls = new Map();
let jobsController;
let healthTimer;
let retryAction;
let dialogTrigger;
let sessionEpoch = 0;
const studio = createStudio({connected:()=>state.connected,notify:notice,error:fail,follow:followTask});

function notice(message, action, error = false, success = false) {
  $('notice').hidden = !message;
  $('notice').classList.toggle('error', error);
  $('notice').classList.toggle('success', success);
  $('notice-text').textContent = message || '';
  $('notice-retry').hidden = !action;
  retryAction = action;
}

function fail(error, retry) {
  if (error.code === 'CANCELLED_REQUEST') return;
  if (error.status === 401) {
    state.connected = false;
    sessionEpoch++;
    studio.reset();
    stopPolling();
    connection();
  }
  notice(explanation(error), error.status === 401 ? connect : retry, true);
}

function connection() {
  $('connection').textContent = state.connected ? 'Local session' : state.connecting ? 'Connecting…' : 'Disconnected';
  $('connection').className = `pill ${state.connected ? 'good' : 'neutral'}`;
  $('session-button').textContent = state.connected ? 'Disconnect' : 'Connect';
  $('session-button').disabled = state.connecting;
  updateActions();
}

function updateActions() {
  const board = state.boards.find(item => item.id === state.boardId);
  const active = [...state.tasks.values()].some(task => task.entity_id === state.boardId && !terminal(task));
  for (const button of document.querySelectorAll('.refresh-button')) {
    const reason = !state.connected ? 'Connect your local session first.' : !board?.enabled ? 'This source is not enabled.'
      : state.sending ? 'Sending refresh request…' : active ? 'A source refresh is already in progress. Follow it in Activity.'
        : !state.health?.worker.ready && !state.command ? 'Source worker is stopped. Start CareerLens with python -m app.dev.' : '';
    button.disabled = Boolean(reason);
    button.title = reason;
    button.textContent = state.sending ? 'Starting refresh…' : state.command ? 'Retry refresh request ↻' : active ? 'Refresh in progress…' : 'Refresh listings ↻';
  }
  $('source-select').disabled = !state.connected || !state.boards.length || state.sending || Boolean(state.command);
  $('check-task').disabled = !state.connected;
}

function sourceOptions() {
  $('source-select').replaceChildren(...state.boards.map(board => node('option', {value: board.id}, board.employer)));
  if (state.boardId) $('source-select').value = state.boardId;
}

function draw() {
  renderHealth(state.health);
  renderSource(state, refresh);
  renderJobs(state, openJob);
  renderTasks(state, selectTask);
  updateActions();
}

async function health() {
  try { state.health = await request('/health', {validate: 'health'}); }
  catch (error) { state.health = null; fail(error, health); }
  renderHealth(state.health);
  updateActions();
}

function scheduleHealth() {
  clearTimeout(healthTimer);
  if (!state.connected) return;
  healthTimer = setTimeout(async () => {
    if (document.visibilityState === 'visible') await health();
    scheduleHealth();
  }, 30000);
}

async function connect() {
  if (state.connecting) return;
  state.connecting = true;
  connection();
  notice('Connecting to your private local workspace…');
  try {
    const session = await request('/api/v1/browser-session', {method: 'POST', body: {}, validate: 'session'});
    if (!session.connected) throw new Error('Session not established');
    state.connected = true;
    notice(null);
    const results = await Promise.allSettled([health(), loadSources()]);
    for (const result of results) if (result.status === 'rejected') fail(result.reason, connect);
    if (state.connected) await studio.load();
    scheduleHealth();
  } catch (error) {
    state.connected = false;
    sessionEpoch++;
    fail(error, connect);
  } finally {
    state.connecting = false;
    connection();
  }
}

async function disconnect() {
  try {
    await request('/api/v1/browser-session/disconnect', {method: 'POST', body: {}, validate: 'session'});
    state.connected = false;
    sessionEpoch++;
    jobsController?.abort();
    studio.reset();
    stopPolling();
    clearTimeout(healthTimer);
    state.jobs = [];
    state.total = null;
    state.boards = [];
    state.boardId = null;
    state.tasks.clear();
    state.events.clear();
    state.selectedTask = null;
    state.command = null;
    $('task-list').replaceChildren();
    $('task-detail').replaceChildren(node('p', {class: 'muted'}, 'Connect to follow local tasks.'));
    notice('Disconnected. Connect again to use your local workspace.', connect);
    draw();
    connection();
  } catch (error) { fail(error, disconnect); }
}

async function loadSources() {
  const epoch = sessionEpoch;
  const boards = await request('/api/v1/source-boards', {validate: 'boards'});
  if (!state.connected || epoch !== sessionEpoch) return;
  state.boards = boards;
  if (!state.boards.some(b => b.id === state.boardId)) state.boardId = state.boards[0]?.id || null;
  sourceOptions();
  const board = state.boards.find(b => b.id === state.boardId);
  state.stale = Boolean(board?.last_error_code);
  if (state.boardId) await loadJobs(true);
  else { state.jobs = []; state.total = 0; draw(); }
}

async function loadJobs(reset = false) {
  if (!state.connected || !state.boardId) return;
  jobsController?.abort();
  const controller = new AbortController();
  jobsController = controller;
  state.jobsLoading = true;
  state.jobsError = null;
  renderJobs(state, openJob);
  try {
    const offset = reset ? 0 : state.jobs.length;
    const page = await request(`/api/v1/source-boards/${state.boardId}/jobs?limit=12&offset=${offset}`,
      {validate: 'jobs', signal: controller.signal});
    if (controller.signal.aborted || !state.connected) return;
    if (page.offset !== offset || (page.items.length === 0 && offset < page.total)) {
      throw Object.assign(new Error(), {code: 'INVALID_RESPONSE'});
    }
    // Never concatenate different snapshot generations after a background source refresh.
    if (!reset && page.last_refreshed_at !== state.lastRefreshed) {
      notice('The source snapshot changed. Reloading the first page so listings stay consistent.');
      return await loadJobs(true);
    }
    state.jobs = reset ? page.items : [...new Map([...state.jobs, ...page.items].map(job => [job.id, job])).values()];
    state.total = page.total;
    state.lastRefreshed = page.last_refreshed_at;
    updateFilterOptions(state.jobs);
  } catch (error) {
    if (controller.signal.aborted) return;
    state.jobsError = explanation(error);
    fail(error, () => loadJobs(reset));
  } finally {
    if (controller === jobsController) {
      state.jobsLoading = false;
      renderSource(state, refresh);
      renderJobs(state, openJob);
      updateActions();
    }
  }
}

async function refresh() {
  if (state.sending || !state.connected) return;
  const board = state.boards.find(b => b.id === state.boardId);
  if (!board?.enabled || [...state.tasks.values()].some(t => t.entity_id === board.id && !terminal(t))) return;
  if (!state.command && !state.health?.worker.ready) return;
  // Keep both key and exact payload until an ambiguous response is resolved.
  state.command ||= {key: crypto.randomUUID(), boardId: board.id, payload: {expected_revision: board.revision}};
  state.sending = true;
  updateActions();
  notice('Requesting a source refresh…');
  try {
    const command = state.command;
    const reference = await request(`/api/v1/source-boards/${command.boardId}/refresh`, {
      method: 'POST', body: command.payload, key: command.key, validate: 'reference',
    });
    state.command = null;
    notice('Refresh queued. Follow its progress in Activity. Stored listings remain available.');
    await followTask(reference.task_id);
  } catch (error) {
    // A server error, timeout or malformed response may still have enqueued the command.
    if (error.status >= 400 && error.status < 500) state.command = null;
    fail(error, state.command ? refresh : async () => { await loadSources(); notice('Source reloaded. You can start a new refresh.'); });
  } finally {
    state.sending = false;
    updateActions();
  }
}

function stopPolling() {
  for (const poll of polls.values()) clearTimeout(poll.timer);
  polls.clear();
}

async function readTask(id) {
  const epoch = sessionEpoch;
  const task = await request(`/api/v1/tasks/${id}`, {validate: 'task'});
  if (!state.connected || epoch !== sessionEpoch) return task;
  const previous = state.tasks.get(id);
  state.tasks.set(id, task);
  try {
    const events = await request(`/api/v1/tasks/${id}/events`, {validate: 'events'});
    if (!state.connected || epoch !== sessionEpoch) return task;
    state.events.set(id, events);
  }
  catch (error) { state.events.delete(id); fail(error, () => followTask(id)); }
  renderTasks(state, selectTask);
  updateActions();
  const newlyTerminal = terminal(task) && (!previous || !terminal(previous));
  if (task.kind !== 'source_refresh') {
    await studio.taskChanged(task,newlyTerminal);
  } else if (newlyTerminal) {
    if (task.status === 'SUCCEEDED') {
      notice(`Refresh complete. ${task.result.listing_count} listings stored${task.result.data_origin === 'fixture' ? ' from controlled fixture data' : ' from the live source'}.`, undefined, false, true);
      try { await loadSources(); } catch (error) { fail(error, loadSources); }
    } else {
      state.stale = true;
      notice(task.status === 'FAILED' ? `Refresh failed (${task.error_code || 'unknown error'}). Earlier stored listings are kept. See Activity for details.`
        : 'Refresh cancelled. Earlier stored listings are kept.', undefined, true);
      renderJobs(state, openJob);
    }
  }
  return task;
}

async function followTask(id) {
  if (!state.connected) return;
  const old = polls.get(id);
  if (old) clearTimeout(old.timer);
  const poll = {count: 0, failures: 0, timer: null};
  polls.set(id, poll);
  state.selectedTask = id;
  async function tick() {
    if (polls.get(id) !== poll || !state.connected) return;
    try {
      const task = await readTask(id);
      poll.failures = 0;
      if (terminal(task)) { polls.delete(id); return; }
    } catch (error) {
      poll.failures++;
      fail(error, () => followTask(id));
      if ([401, 403, 404].includes(error.status) || poll.failures >= 3) { polls.delete(id); return; }
    }
    if (++poll.count >= 150) {
      polls.delete(id);
      notice('Automatic checks paused after 150 attempts. The backend task may still be running. Select Check status in Activity.', () => followTask(id));
      return;
    }
    if (polls.get(id) === poll) poll.timer = setTimeout(tick, document.hidden ? 10000 : 2000);
  }
  await tick();
}

function selectTask(id) {
  state.selectedTask = id;
  renderTasks(state, selectTask);
  if (!state.events.has(id)) followTask(id);
}

function openJob(job, source) {
  dialogTrigger = document.activeElement;
  showJob(job, source);
}

function navigate(focus = false) {
  const name = ['overview', 'explore', 'activity', 'studio'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
  for (const view of ['overview', 'explore', 'activity', 'studio']) $(view).hidden = view !== name;
  for (const link of document.querySelectorAll('[data-view]')) {
    if (link.dataset.view === name) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  $('breadcrumb').textContent = {overview: 'Overview', explore: 'Explore jobs', activity: 'Activity', studio: 'Resume Studio'}[name];
  document.title = `${$('breadcrumb').textContent} · CareerLens`;
  if (focus) $(`${name}-title`).focus();
}

$('notice-retry').addEventListener('click', () => Promise.resolve(retryAction?.()).catch(error => fail(error)));
$('session-button').addEventListener('click', () => state.connected ? disconnect() : connect());
document.querySelector('#explore .refresh-button').addEventListener('click', refresh);
$('source-select').addEventListener('change', async () => {
  state.boardId = $('source-select').value;
  state.jobs = []; state.total = null;
  state.stale = Boolean(state.boards.find(b => b.id === state.boardId)?.last_error_code);
  await loadJobs(true);
});
for (const id of ['job-search', 'type-filter', 'location-filter']) $(id).addEventListener(id === 'job-search' ? 'input' : 'change', () => renderJobs(state, openJob));
$('clear-filters').addEventListener('click', () => {
  for (const id of ['job-search', 'type-filter', 'location-filter']) $(id).value = '';
  renderJobs(state, openJob);
});
$('load-more').addEventListener('click', () => { if (!state.jobsLoading) loadJobs(); });
$('retry-jobs').addEventListener('click', () => loadJobs(true));
$('close-dialog').addEventListener('click', () => $('job-dialog').close());
$('job-dialog').addEventListener('click', event => {
  const bounds = $('job-dialog').getBoundingClientRect();
  if (event.target === $('job-dialog') && (event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom)) $('job-dialog').close();
});
$('job-dialog').addEventListener('keydown', event => {
  if (event.key !== 'Tab') return;
  const controls = [...$('job-dialog').querySelectorAll('button:not(:disabled), a[href]')];
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
$('job-dialog').addEventListener('close', () => {
  if (dialogTrigger?.isConnected) dialogTrigger.focus();
  else $('explore-title').focus();
});
$('check-task').addEventListener('click', () => state.selectedTask && followTask(state.selectedTask));
$('task-lookup').addEventListener('submit', event => {
  event.preventDefault();
  const id = $('task-id').value.trim();
  if (!uuid(id)) { notice('Enter a valid task UUID from this local workspace.', undefined, true); $('task-id').focus(); return; }
  followTask(id);
});
window.addEventListener('hashchange', () => navigate(true));
window.addEventListener('pagehide', () => { stopPolling(); clearTimeout(healthTimer); jobsController?.abort(); });
window.addEventListener('pageshow', event => { if (event.persisted) connect(); });
navigate();
draw();
connect();
