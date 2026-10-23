import {$, node, button, empty, date, words, pill, taskKind, company, officialURL} from './dom.js';

export function renderHealth(health) {
  const values = [
    ['⌁', 'Local API', health ? (health.api_ready ? 'Connected' : 'Unavailable') : 'Unknown', health?.api_ready],
    ['▤', 'Database', health ? (health.database_ready ? 'Ready' : 'Unavailable') : 'Unknown', health?.database_ready],
    ['↻', 'Source worker', health ? (health.worker.ready ? 'Ready to refresh' : 'Stopped · start CareerLens') : 'Unknown', health?.worker.ready],
  ];
  $('system-status').replaceChildren(...values.map(([icon, label, value, ready]) =>
    node('div', {class: 'status-card'}, node('span', {class: 'status-symbol', 'aria-hidden': 'true'}, icon),
      node('div', {}, node('span', {class: 'status-label'}, label), node('span', {class: `status-value ${ready ? 'good' : 'warning'}`}, value)))));
  $('version').textContent = health ? `Backend v${health.version}` : 'System status unknown';
}

export function renderSource(state, refresh) {
  const source = state.boards.find(b => b.id === state.boardId);
  const container = $('source-summary');
  if (!source) {
    container.replaceChildren(empty(state.connected ? 'No source configured' : 'Your local workspace',
      state.connected ? 'There are no configured job sources.' : 'Connect to load your sources and stored listings.'));
    return;
  }
  const refreshButton = button('Refresh listings ↻', refresh, 'button secondary refresh-button');
  const count = state.total === null ? '—' : state.total;
  container.replaceChildren(
    node('div', {class: 'company-row'}, company(source.employer), node('div', {},
      node('h3', {}, source.employer), node('p', {}, `${words(source.family)} · ${source.slug}`)),
      pill(source.enabled ? 'Enabled' : 'Disabled', source.enabled ? 'good' : 'neutral')),
    node('div', {class: 'source-stats'}, node('div', {}, node('strong', {}, count), node('span', {}, 'stored listings')),
      node('div', {}, node('strong', {}, words(source.family)), node('span', {}, 'source platform'))),
    node('p', {class: 'muted'}, `Last refreshed: ${date(source.refreshed_at)}`),
    ...(!state.health?.worker.ready ? [node('p', {class: 'muted'}, 'Refresh is unavailable until the source worker is ready. Start CareerLens with python -m app.dev.')] : []),
    ...(source.last_error_code ? [node('p', {class: 'inline-warning'}, `Source error: ${source.last_error_code}. Earlier stored results are retained.`)] : []),
    node('div', {class: 'panel-actions'}, refreshButton, node('a', {href: '#explore', class: 'small-link'}, 'Browse listings ↗')),
  );
  $('nav-count').textContent = state.total === null ? '' : state.total;
  $('source-state').textContent = `${source.enabled ? 'Enabled' : 'Disabled'} · Last refreshed: ${date(source.refreshed_at)}`;
}

export function updateFilterOptions(jobs) {
  for (const [id, field, label] of [['type-filter', 'employment_type', 'All types'], ['location-filter', 'location', 'All locations']]) {
    const select = $(id);
    const current = select.value;
    const values = [...new Set(jobs.map(job => job[field]).filter(Boolean))].sort();
    select.replaceChildren(node('option', {value: ''}, label), ...values.map(v => node('option', {value: v}, v)));
    if (values.includes(current)) select.value = current;
  }
}

export function renderJobs(state, openDetail) {
  const query = $('job-search').value.trim().toLowerCase();
  const type = $('type-filter').value;
  const location = $('location-filter').value;
  const filtered = state.jobs.filter(job => (!type || job.employment_type === type) && (!location || job.location === location)
    && (!query || [job.title, job.employer, job.location, job.employment_type].filter(Boolean).join(' ').toLowerCase().includes(query)));
  $('job-list').setAttribute('aria-busy', String(state.jobsLoading));
  $('results-count').textContent = state.total === null ? 'Listings not loaded' : `${filtered.length} shown · ${state.jobs.length} loaded · ${state.total} stored`;
  $('retrieval-time').textContent = state.lastRefreshed ? `Snapshot: ${date(state.lastRefreshed)}` : '';
  $('load-more').hidden = state.total === null || state.jobs.length >= state.total;
  $('load-more').disabled = state.jobsLoading || !state.connected;
  $('load-more').textContent = state.jobsLoading ? 'Loading…' : 'Load more listings';
  $('retry-jobs').hidden = !state.jobsError;
  $('jobs-warning').hidden = !state.stale && !state.jobsError;
  $('jobs-warning').textContent = state.jobsError || 'The last refresh did not complete. These are earlier stored results; check Activity before relying on them.';
  if (!state.jobs.length && state.jobsLoading) {
    $('job-list').replaceChildren(node('p', {class: 'loading-label', role: 'status'}, 'Loading stored listings…'),
      ...Array.from({length: 3}, () => node('div', {class: 'loading-card', 'aria-hidden': 'true'})));
  } else if (!filtered.length) {
    $('job-list').replaceChildren(empty(
      !state.connected ? 'Connect to explore' : state.jobsError ? 'Listings could not be loaded' : state.jobs.length ? 'Nothing in this view yet' : 'A clean slate',
      !state.connected ? 'Reconnect your local workspace to load listings.' : state.jobsError ? 'Try loading again. Any previous data is kept.'
        : state.jobs.length ? 'Try another keyword or clear your filters. You can also load more listings.'
          : 'No listings are stored for this source. Refresh listings when the worker is ready.'));
  } else {
    const source = state.boards.find(b => b.id === state.boardId);
    $('job-list').replaceChildren(...filtered.map(job => {
      const open = () => openDetail(job, source);
      return node('article', {class: 'job-card'}, node('div', {class: 'company-row'}, company(job.employer), node('p', {}, job.employer)),
        node('h3', {}, button(job.title, open)),
        node('div', {class: 'job-meta'}, node('span', {}, job.location || 'Location not specified'), node('span', {}, job.employment_type || 'Type not specified')),
        node('div', {class: 'job-card-bottom'}, node('span', {}, `${words(source?.family || 'lever')} · ${date(job.fetched_at, true)}`), button('View details ↗', open)));
    }));
  }
}

export function showJob(job, source) {
  const detail = $('job-detail');
  const list = node('dl', {class: 'detail-list'});
  for (const [label, value] of [['Company', job.employer], ['Location', job.location || 'Not specified'],
    ['Employment type', job.employment_type || 'Not specified'], ['Source', words(source?.family || 'lever')],
    ['Retrieved', date(job.fetched_at)], ['Listing ID', job.external_id]]) {
    list.append(node('div', {}, node('dt', {}, label), node('dd', {}, value)));
  }
  const links = node('div', {class: 'dialog-links'});
  for (const [value, apply, label] of [[job.source_url, false, 'View on employer website ↗'], [job.apply_url, true, 'Employer application page ↗']]) {
    const safe = officialURL(value, apply);
    if (safe) links.append(node('a', {href: safe, target: '_blank', rel: 'noopener noreferrer', class: `button ${apply ? 'secondary' : 'primary'}`}, label));
  }
  detail.replaceChildren(node('div', {class: 'company-row'}, company(job.employer), node('span', {class: 'muted'}, job.employer)),
    node('h2', {id: 'dialog-title', class: 'dialog-title'}, job.title), list,
    node('p', {class: 'dialog-note'}, 'This is a stored listing summary. Read the full description and check current availability on the employer website.'),
    ...(links.childElementCount ? [links] : [node('p', {class: 'inline-warning'}, 'The destination could not be verified. No external link is available.')]),
    node('p', {class: 'dialog-disclaimer'}, 'Links open an external employer page. CareerLens has not prepared or submitted an application.'));
  $('job-dialog').showModal();
  $('close-dialog').focus();
}

const taskLabels = {source_refresh:'Source refresh',resume_parse:'Resume extraction',job_search:'Job search',jd_analysis:'Job analysis',resume_generate:'Resume generation'};
function taskContent(task) {
  const progress = node('progress', {class: 'task-progress', max: 100, value: task.progress, 'aria-label': 'Task progress'}, `${task.progress}%`);
  return [node('div', {class: 'task-summary'}, node('strong', {}, taskLabels[task.kind]), pill(words(task.status), taskKind(task))), progress,
    node('p', {class: 'task-description'}, `${task.progress}% · ${words(task.current_step)} · Attempt ${task.attempts} of ${task.max_attempts}`),
    ...(task.retry_at && task.status === 'WAITING' ? [node('p', {class: 'inline-warning'}, `Waiting for retry at ${date(task.retry_at)}.`)] : []),
    ...(task.status === 'FAILED' ? [node('p', {class: 'inline-warning'}, task.kind === 'source_refresh'
      ? `Refresh failed: ${task.error_code || 'Unknown error'}. Earlier stored listings are kept. Check the source or development terminal before starting another refresh.`
      : `Processing failed: ${task.error_code || 'Unknown error'}. No unverified result is published. Review Resume Studio or the development terminal.`)] : []),
    ...(task.status === 'CANCELLED' ? [node('p', {class: 'task-description'}, 'This task was cancelled. No successful refresh is reported.')] : []),
    ...(task.result && task.status === 'SUCCEEDED' ? [node('p', {class: 'task-description'}, task.kind === 'source_refresh'
      ? `${task.result.listing_count} listings stored · ${task.result.data_origin === 'live' ? 'Live source' : 'Controlled fixture data'}`
      : task.kind === 'job_search' ? `${task.result.result_count} results · ${words(task.result.state)}` : 'Saved result available in Resume Studio.')] : []),
  ];
}

export function renderTasks(state, selectTask) {
  const tasks = [...state.tasks.values()].reverse();
  $('recent-activity').replaceChildren(...(tasks.length ? [...taskContent(tasks[0]), node('a', {href: '#activity', class: 'small-link activity-link'}, 'Follow task activity ↗')]
    : [empty('A fresh start', 'Refresh a source to follow its progress here.')]));
  $('task-list').replaceChildren(...(tasks.length ? tasks.map(task => {
    const item = button('', () => selectTask(task.id), 'task-item');
    item.setAttribute('aria-pressed', String(task.id === state.selectedTask));
    item.append(node('div', {class: 'task-summary'}, node('strong', {}, taskLabels[task.kind]), pill(words(task.status), taskKind(task))),
      node('p', {}, `${date(task.created_at)} · ${task.progress}% · ${words(task.current_step)}`));
    return item;
  }) : [empty('No tasks followed yet', 'Start a refresh or look up a task above.')]));
  const current = state.tasks.get(state.selectedTask);
  $('check-task').hidden = !current;
  if (!current) return;
  const stats = node('dl', {class: 'task-stats'});
  for (const [name, value] of [['Created', date(current.created_at)], ['Updated', date(current.updated_at)],
    ['Completed', current.finished_at ? date(current.finished_at) : 'Not completed'], ['Safe error code', current.error_code || 'None']]) {
    stats.append(node('div', {}, node('dt', {}, name), node('dd', {}, value)));
  }
  const events = state.events.get(current.id);
  const timeline = node('ol', {class: 'timeline', 'aria-label': 'Task events'},
    ...(events || []).map(event => node('li', {}, words(event.kind), node('time', {datetime: event.created_at}, date(event.created_at)))));
  $('task-detail').replaceChildren(...taskContent(current), stats, node('p', {class: 'task-id'}, `Task ID: ${current.id}`),
    node('h3', {class: 'stack-gap'}, 'Event history'), events ? timeline : node('p', {class: 'muted'}, 'Events unavailable. Select Check status to retry.'));
}
