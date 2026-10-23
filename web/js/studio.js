import {request, terminal} from './api.js';
import {$, node, button, date, words, pill, company} from './dom.js';

const KINDS = ['name','email','phone','links','summary','skills','education','projects','experience','certifications','achievements','other'];
const TASK_LABELS = {resume_parse:'Resume extraction',job_search:'Job search',jd_analysis:'Job analysis',resume_generate:'Resume generation'};
const GUIDANCE = {
  PROVIDER_COOLDOWN:'Groq requested a cooldown. Wait until the reported retry time before starting a new generation.',
  MISSING_API_KEY:'Add your Groq key to the private .env file and restart CareerLens. No other provider is used.',
  RATE_LIMIT_OR_QUOTA_EXHAUSTED:'Groq is rate limited or out of quota. Wait before explicitly starting a new generation. No paid fallback is used.',
  PROVIDER_TIMEOUT:'Groq timed out. The task failed safely; no unverified PDF was published.',
  PROVIDER_NETWORK_ERROR:'Groq could not be reached. Check your connection before starting another generation.',
  PROVIDER_OUTCOME_UNKNOWN:'The worker stopped during a Groq request. That call is not replayed automatically. Start a new generation explicitly if you want to retry.',
  PROFILE_UNCONFIRMED:'Confirm your profile before continuing.',
  STALE_PROFILE:'Your profile changed. Load and confirm the latest version, then search and analyse again.',
  STALE_JOB:'The selected job snapshot changed. Refresh the source and search again.',
  VERIFICATION_FAILED:'Unsupported or uncertain content blocked this document. No tailored PDF was published.',
  VERIFIER_RESPONSE_INVALID:'Factual review did not return a trustworthy result. No PDF was published.',
  NO_EXTRACTABLE_TEXT:'This PDF has no extractable text. Use a text-based PDF; OCR is not applied.',
  ENCRYPTED_PDF:'Encrypted PDFs are not supported. Export an unencrypted text PDF.',
  TOO_MANY_PAGES:'The PDF exceeds 10 pages.',
  PDF_JAVASCRIPT_ACTION:'This PDF contains JavaScript. Export a text PDF with scripts disabled.',
  PDF_LAUNCH_ACTION:'This PDF can launch an application or file. Export it without launch actions.',
  PDF_EXTERNAL_FILE_ACTION:'This PDF opens another file or embedded document. Export it without external-file actions.',
  PDF_AUTOMATIC_EXTERNAL_ACTION:'This PDF automatically opens an external link. Disable automatic link actions; normal clickable web links are supported.',
  PDF_UNSAFE_LINK_ACTION:'This PDF uses an unsupported link protocol. Use ordinary web, email or phone links.',
  PDF_EMBEDDED_FILES:'This PDF contains attached or embedded files. Export the resume without attachments.',
  PDF_XFA_CONTENT:'This PDF contains an XFA interactive form. Export a standard text PDF.',
  PDF_INTERACTIVE_MEDIA:'This PDF contains interactive media. Export a standard text PDF without media.',
  PDF_UNSUPPORTED_NAMED_ACTION:'This PDF requests a viewer command beyond page navigation. Export it without interactive viewer commands.',
  PDF_UNSUPPORTED_ACTION:'This PDF contains an unsupported interactive action. Export a standard text PDF with interactive actions disabled.',
  PDF_INVALID_DESTINATION:'This PDF has an invalid page destination. Re-export it as a standard text PDF.',
  PDF_ACTION_LIMIT:'This PDF has an excessively complex or cyclic action structure. Re-export it as a standard text PDF.',
  PDF_TOO_LARGE:'Choose a PDF no larger than 5 MiB.',
  UNREADABLE_PDF:'The PDF is corrupt or unreadable. Export a fresh text-based PDF.',
};

export function createStudio({connected, notify, error, follow}) {
  const state = {profile:null,profiles:[],search:null,analysis:null,generation:null,generations:[],busy:false,dirty:false,
    additions:[],file:null,active:new Map(),changeRole:false,epoch:0,pending:null,profileRead:0,analysisRead:0,generationRead:0};
  let loading = false;

  function guidance(code) { return GUIDANCE[code] || `Processing failed (${code || 'unknown error'}). Check Activity and the development terminal before retrying.`; }
  function handle(errorValue, retry) {
    if (GUIDANCE[errorValue.code]) notify(GUIDANCE[errorValue.code],retry,true);
    else error(errorValue,retry);
  }
  function current() { return state.profile && state.profiles[0]?.id === state.profile.id; }
  function ready() { return current() && state.profile.confirmed_at && !state.dirty; }
  function active(kind) { return [...state.active.values()].some(task => task.kind === kind && !terminal(task)); }
  function actions() {
    const usable = connected() && !state.busy;
    const pendingUpload=state.pending?.path==='/api/v1/profiles';
    const ai=$('profile-parsing-mode').value==='groq';
    $('profile-ai-consent-box').hidden=!ai;
    $('profile-parsing-mode').disabled=!usable || active('resume_parse') || pendingUpload;
    $('profile-ai-consent').disabled=!usable || active('resume_parse') || pendingUpload;
    $('upload-resume').disabled = !usable || !state.file || active('resume_parse') || pendingUpload || (ai && !$('profile-ai-consent').checked);
    $('resume-file').disabled = !usable || active('resume_parse') || pendingUpload;
    $('profile-version').disabled = !usable || !state.profiles.length || state.dirty;
    $('save-profile').disabled = !usable || !current() || !state.dirty;
    $('confirm-profile').disabled = !usable || !current() || state.dirty || Boolean(state.profile?.confirmed_at);
    $('discard-profile').hidden = !state.dirty;
    $('find-matches').disabled = !usable || !ready() || active('job_search');
    $('generate-resume').disabled = !usable || !ready() || !state.analysis || state.analysis.profile_version_id !== state.profile?.id
      || !$('groq-consent').checked || active('resume_generate') || state.pending !== null;
    $('generation-history').disabled = !usable || !state.generations.length;
    $('reload-studio').disabled = !usable || state.dirty;
    $('matching-help').textContent = !ready() ? 'Confirm your latest saved profile before searching. Save unsaved corrections first.'
      : 'Searches use current persisted source snapshots. Refresh the source in Explore for a newer fetch; no location or eligibility defaults are applied.';
    $('profile-save-note').textContent = state.dirty ? 'Unsaved corrections. Save a new version, then confirm it before proceeding.'
      : state.profile?.confirmed_at ? 'This version is confirmed. Further corrections create a new version that needs confirmation.'
        : 'Review every extracted line and its section, then confirm this saved version.';
  }
  function markDirty() { state.dirty = true; actions(); }

  // A lost mutation response retains its exact key/body until an explicit retry resolves it.
  async function mutate(path, body, validate = 'reference', method = 'POST', success) {
    if (state.busy || !connected()) return;
    if (state.pending && state.pending.path !== path) {
      notify('Resolve the previous request with Try again before starting another action.', () => retryMutation(),true);
      return;
    }
    state.pending ||= {path,body,validate,method,key:crypto.randomUUID(),success};
    return retryMutation();
  }
  async function retryMutation() {
    if (!state.pending || state.busy || !connected()) return;
    const pending = state.pending, epoch = state.epoch;
    state.busy = true; actions();
    try {
      const value = await request(pending.path,{method:pending.method,body:pending.body,key:pending.key,validate:pending.validate});
      if (epoch !== state.epoch || !connected()) return;
      state.pending = null;
      if (pending.success) await pending.success(value);
      else await follow(value.task_id);
    } catch (problem) {
      if (epoch !== state.epoch) return;
      if (problem.status >= 400 && problem.status < 500) state.pending = null;
      handle(problem,state.pending ? retryMutation : load);
    } finally { if (epoch === state.epoch) {state.busy=false;actions();} }
  }

  async function load({profileId,searchId,generationId,restoreTasks=true} = {}) {
    if (!connected() || loading) return;
    loading = true;
    const epoch = state.epoch;
    try {
      const results = await Promise.allSettled([
        request('/api/v1/profiles',{validate:'profiles'}), request('/api/v1/searches',{validate:'searches'}),
        request('/api/v1/resume-generations',{validate:'generations'}), request('/api/v1/studio/tasks',{validate:'references'}),
      ]);
      if (epoch !== state.epoch || !connected()) return;
      for (const result of results) if (result.status === 'rejected') throw result.reason;
      const [profiles,searches,generations,references] = results.map(result => result.value);
      state.profiles=profiles; state.generations=generations;
      renderVersionOptions(); renderHistoryOptions();
      const wanted=profileId || state.profile?.id || profiles[0]?.id;
      if (wanted && !state.dirty) await chooseProfile(wanted,false);
      else if (profileId && state.dirty) notify('A new parsed profile is ready. Save or discard your unsaved corrections before loading it.');
      const found=searches.find(search => search.id === searchId) || searches.find(search => search.profile_version_id === state.profile?.id);
      if (found && (!state.search || searchId || state.search.profile_version_id !== state.profile?.id)) {
        state.search=found; renderSearch();
        if (found.selected_analysis_id) {
          try { await chooseAnalysis(found.selected_analysis_id); } catch (problem) { if (problem.status !== 404) throw problem; }
        }
      }
      if (generationId || (!state.generation && generations[0])) await chooseGeneration(generationId || generations[0].id);
      if (restoreTasks) {
        for (const reference of references.slice(0,5)) {
          const task=await request(`/api/v1/tasks/${reference.task_id}`,{validate:'task'});
          if (epoch !== state.epoch || !connected()) return;
          if (!terminal(task)) { state.active.set(task.id,task); follow(task.id); }
        }
      }
      actions();
    } catch (problem) { if (epoch === state.epoch) handle(problem,load); }
    finally { loading=false; }
  }

  function renderVersionOptions() {
    $('profile-version').replaceChildren(...(state.profiles.length ? state.profiles.map(profile =>
      node('option',{value:profile.id},`Version ${profile.version} · ${profile.confirmed_at ? 'Confirmed' : 'Needs review'} · ${date(profile.created_at)}`))
      : [node('option',{},'No saved profiles yet')]));
    if (state.profile) $('profile-version').value=state.profile.id;
  }
  async function chooseProfile(id) {
    const epoch=state.epoch, sequence=++state.profileRead;
    const profile=await request(`/api/v1/profiles/${id}`,{validate:'profile'});
    if (epoch !== state.epoch || sequence !== state.profileRead || state.dirty || !connected()) return;
    if (state.profile && state.profile.id !== id) {state.search=null;state.analysis=null;renderSearch();$('job-analysis').hidden=true;$('tailoring-panel').hidden=true;}
    if (state.profile?.id !== id) $('groq-consent').checked=false;
    state.profile=profile;state.dirty=false;state.additions=[];
    $('profile-version').value=id;
    renderProfile();actions();
  }
  function kindSelect(id,value) {
    return node('select',{id,'aria-label':'Fact section'},...KINDS.map(kind => node('option',{value:kind,...(kind === value ? {selected:''}:{})},words(kind))));
  }
  function factEditor(fact,index,addition=false) {
    const id=`fact-${fact.id}`, sectionId=`kind-${fact.id}`;
    const area=node('textarea',{id,class:'fact-text',rows:2,maxlength:4000,'data-fact-id':fact.id},fact.text);
    const select=kindSelect(sectionId,fact.kind);
    area.addEventListener('input',markDirty);select.addEventListener('change',markDirty);
    const source=fact.source_ref;
    const evidence=source ? node('details',{class:'fact-source'},node('summary',{},`Extracted · Page ${source.page} · offsets ${source.start_offset}–${source.end_offset}`),
      node('blockquote',{},source.source_text),node('code',{},`${fact.extraction_method==='groq'?'Groq structured · exact source':'Local extraction'} · Fact ${fact.id}`))
      : node('p',{class:'fact-source'},addition ? 'Explicit user addition · requires confirmation' : 'Explicit user fact · source PDF text is retained separately');
    if (!current()) {area.disabled=true;select.disabled=true;}
    return node('div',{class:'fact-editor'},node('label',{for:id},`${words(fact.kind)} · ${index+1}`),node('div',{class:'fact-controls'},select,area),evidence);
  }
  function renderProfile() {
    const profile=state.profile;
    $('profile-review').hidden=!profile;
    if (!profile) return;
    $('profile-status').replaceWith(Object.assign(pill(profile.confirmed_at ? 'Confirmed' : 'Needs review',profile.confirmed_at?'good':'warning'),{id:'profile-status'}));
    $('profile-version-note').textContent=`Version ${profile.version} · revision ${profile.revision}${current() ? ' · latest version' : ' · historical version; select the latest to edit or generate'}`;
    const parsing=profile.parsing;
    $('profile-parsing-note').textContent=parsing?.mode==='groq'
      ? `${parsing.provider==='controlled_fixture'?'Controlled AI fixture':'Groq structured profile'} · ${parsing.model} · Every fact was checked against exact PDF text; contact extraction stayed local.`
      : parsing?.mode==='local_fallback' ? `Local-only extraction · AI unavailable or evidence rejected (${parsing.error_code}). No model facts were accepted.`
        : 'Local-only extraction · No Groq call was made for profile parsing.';
    $('profile-links').replaceChildren(...(profile.source_artifact_id ? [node('a',{class:'small-link',href:`/api/v1/artifacts/${profile.source_artifact_id}`,download:'original-resume.pdf'},'Download original PDF ↗')] : []));
    $('profile-warnings').replaceChildren(...profile.warnings.map(warning => node('p',{},warning)));
    $('profile-facts').replaceChildren(...KINDS.filter(kind => profile.facts.some(fact=>fact.kind===kind)).map(kind => {
      const group=node('details',{class:'fact-group',open:''},node('summary',{},`${words(kind)} · ${profile.facts.filter(f=>f.kind===kind).length} facts`));
      for (const [index,fact] of profile.facts.entries()) if (fact.kind===kind) group.append(factEditor(fact,index));
      return group;
    }));
    $('profile-source').replaceChildren(...profile.pages.map(page => node('div',{},node('h3',{},`Page ${page.page}`),node('pre',{},page.text))));
  }
  function corrections() {
    const values=[];
    for (const fact of [...state.profile.facts,...state.additions]) {
      const text=$(`fact-${fact.id}`).value.trim(),kind=$(`kind-${fact.id}`).value;
      if (!text) throw new Error('EMPTY_FACT');
      if (state.additions.includes(fact)) values.push({fact_id:null,kind,text});
      else if (text !== fact.text || kind !== fact.kind) values.push({fact_id:fact.id,kind,text});
    }
    return values;
  }

  function renderSearch() {
    const search=state.search;
    $('role-decision').hidden=!search || search.state !== 'NEEDS_ROLE_DECISION';
    $('role-decision').replaceChildren();
    $('match-results').replaceChildren();
    if (!search) return;
    $('preferred-role').value=search.title;
    if (search.state === 'NEEDS_ROLE_DECISION') {
      $('role-decision').append(node('div',{class:'role-warning'},node('h3',{},'Your direction is still your choice'),node('p',{},search.warning),
        node('div',{class:'studio-actions'},button('Continue with requested role',()=>mutate(`/api/v1/searches/${search.id}/decision`,
          {expected_revision:search.revision,decision:'continue_requested_role'}),'button secondary'),
          button('Change role',()=>{state.changeRole=true;$('preferred-role').focus();notify('Enter the new title, then choose Find matching jobs to record your decision.');},'text-button'))));
      return;
    }
    if (search.state === 'RUNNING') { $('match-results').append(node('p',{class:'muted'},'Searching stored snapshots…'));return; }
    if (search.state === 'FAILED') { $('match-results').append(node('p',{class:'inline-warning'},'Search failed. Inspect the task in Activity before starting a new search.'));return; }
    if (!search.results.length) { $('match-results').append(node('div',{class:'empty'},node('h3',{},'No matching stored jobs'),node('p',{},'This board has no results for these explicit filters. Refresh the source or choose another role; no substitute jobs are invented.')));return; }
    for (const job of search.results) {
      const choose=button('Analyse this job',()=>{
        state.analysis=null;$('groq-consent').checked=false;$('job-analysis').hidden=true;$('tailoring-panel').hidden=true;actions();
        mutate(`/api/v1/searches/${search.id}/selection`,{expected_revision:search.revision,job_snapshot_id:job.id});
      },'button secondary');
      choose.disabled=!ready();
      $('match-results').append(node('article',{class:'studio-match-card'},node('div',{class:'company-row'},company(job.employer),node('span',{},job.employer)),
        node('h3',{},job.title),node('p',{},`${job.location || 'Location not specified'} · ${job.employment_type || 'Type not specified'}`),
        node('p',{},job.match_explanation),node('p',{},`Retrieved ${date(job.fetched_at)} · Source refreshed ${date(job.source_refreshed_at)}. Stored snapshot; availability is unverified.`),choose));
    }
  }

  function evidenceColumn(title,skills) {
    return node('div',{class:'evidence-column'},node('h3',{},title),...skills.map(skill => {
      const evidence=node('details',{},node('summary',{},`${skill.source_fact_ids.length} supporting fact references`));
      evidence.append(node('ul',{},...skill.source_fact_ids.map(id => {
        const fact=state.profile?.facts.find(f=>f.id===id);
        return node('li',{},fact ? `${words(fact.kind)}: ${fact.text}` : `Pinned profile fact: ${id}`);
      })));
      return node('div',{class:'skill-evidence'},node('div',{},node('strong',{},skill.skill),pill(skill.status==='supported'?'Evidence found':'Not evidenced',skill.status==='supported'?'good':'warning')),evidence);
    }),...(!skills.length ? [node('p',{class:'muted'},'No explicit technical skills were classified in this category.')] : []));
  }
  async function chooseAnalysis(id) {
    const epoch=state.epoch, sequence=++state.analysisRead, profileId=state.profile?.id;
    const analysis=await request(`/api/v1/job-analyses/${id}`,{validate:'analysis'});
    if (epoch !== state.epoch || sequence !== state.analysisRead || profileId !== state.profile?.id
      || analysis.profile_version_id !== state.profile?.id || !connected()) return;
    if (state.analysis?.id !== id) $('groq-consent').checked=false;
    state.analysis=analysis;
    const assessment=analysis.assessment;
    $('job-analysis').hidden=false;
    $('job-analysis').replaceChildren(node('p',{class:'eyebrow'},'PINNED JOB ANALYSIS'),node('h2',{},analysis.job_title),
      node('p',{class:'muted'},`${analysis.employer} · snapshot ${analysis.job_snapshot_id} · ${analysis.pipeline_version}`),
      node('div',{class:'coverage-box'},node('strong',{},assessment.coverage===null?'—':`${assessment.coverage}%`),node('p',{},assessment.coverage===null?'No explicit required skills: coverage is not calculated.':'Required skill coverage against confirmed facts.')),
      node('p',{class:'muted'},assessment.scope),node('div',{class:'evidence-grid'},evidenceColumn('Required technical skills',assessment.required),evidenceColumn('Preferred technical skills',assessment.preferred)),
      node('h3',{class:'stack-gap'},'Explicit eligibility observations'),node('ul',{class:'eligibility-list'},...assessment.eligibility.map(value=>node('li',{},value))),
      node('p',{class:'muted'},'Eligibility is kept separate from skill coverage; unstated eligibility is unknown.'),
      node('details',{class:'source-text'},node('summary',{},'Review JD evidence, responsibilities and uncertainties'),
        node('ul',{},...analysis.structured.required_skills.concat(analysis.structured.preferred_skills).map(r=>node('li',{},`${r.canonical_name}: “${r.verbatim_text}” · offsets ${r.source_span.start_offset}–${r.source_span.end_offset}`))),
        node('ul',{},...analysis.structured.responsibilities.map(r=>node('li',{},r.text))),node('ul',{},...analysis.structured.uncertainties.map(t=>node('li',{},t))),node('pre',{},analysis.raw_text)));
    $('tailoring-panel').hidden=false;actions();
    return analysis;
  }

  function renderHistoryOptions() {
    $('generation-history').replaceChildren(...(state.generations.length ? state.generations.map(generation=>node('option',{value:generation.id},
      `${words(generation.state)} · ${date(generation.created_at)} · ${generation.id.slice(0,8)}`)) : [node('option',{},'No generated versions yet')]));
    if (state.generation) $('generation-history').value=state.generation.id;
  }
  async function chooseGeneration(id) {
    const epoch=state.epoch, sequence=++state.generationRead;
    const generation=await request(`/api/v1/resume-generations/${id}`,{validate:'generation'});
    if (epoch !== state.epoch || sequence !== state.generationRead || !connected()) return;
    state.generation=generation;$('generation-history').value=id;
    renderGeneration();
  }
  function renderGeneration() {
    const generation=state.generation,root=$('generation-result');
    root.replaceChildren();
    if (!generation) return;
    root.append(node('p',{class:'generation-meta'},`${generation.employer} · ${generation.job_title}\nPinned profile ${generation.profile_version_id} · analysis ${generation.analysis_id}`));
    const limited=generation.provider_diagnostics?.filter(report=>report.http_status===429).at(-1);
    if (limited) root.append(node('p',{class:'inline-warning'},`Groq reported ${words(limited.limiting_factor)} for ${limited.model}. ${limited.retry_not_before ? `Retry after ${date(limited.retry_not_before)}.` : 'No reliable retry time was supplied.'} Fallback decision: ${words(limited.fallback_decision || 'not eligible')}.`));
    if (generation.profile_version_id !== state.profile?.id) root.append(node('p',{class:'inline-warning'},'Historical result: this resume belongs to a different profile version. It has not been updated to your current profile.'));
    if (generation.state !== 'VERIFIED') {
      root.append(node('p',{class:'inline-warning'},generation.error_code ? guidance(generation.error_code) : `${words(generation.state)}. Follow the task in Activity; no verified PDF is available yet.`));
      return;
    }
    const content=generation.content;
    if (!content || !generation.pdf_artifact_id || !content.verification.pass) {root.append(node('p',{class:'inline-warning'},'This result is incomplete. No PDF is presented as verified.'));return;}
    root.append(pill('Verification passed','good'),node('p',{class:'generation-meta'},`${content.provider==='controlled_fixture'?'CONTROLLED PROVIDER FIXTURE':'Groq live provider'} · ${content.model} · ${content.reverted_item_ids.length} items restored to source wording`));
    if (content.fallback_used) root.append(node('p',{class:'generation-meta'},`Eligible Groq 20B fallback used. Stage models: ${Object.entries(content.stage_models).map(([stage,model])=>`${words(stage)}: ${model}`).join(' · ')}`));
    root.append(node('div',{class:'comparison-grid'},...['original','tailored'].map(kind=>{
      const assessment=content[`${kind}_assessment`];
      return node('div',{},node('h3',{},`${words(kind)} required-skill coverage`),node('strong',{},assessment.coverage===null?'Not calculated':`${assessment.coverage}%`),node('p',{},'The same confirmed qualifications and JD are used. Wording does not add qualifications.'));
    })));
    if (!content.tailored.changes.length) root.append(node('p',{class:'muted'},'No wording changes were verified. The PDF preserves the original confirmed facts.'));
    for (const change of content.tailored.changes) root.append(node('article',{class:'change-card'},
      node('div',{},node('h3',{},words(change.section)),pill(content.reverted_item_ids.includes(change.item_id)?'Restored original':'Verified change',content.reverted_item_ids.includes(change.item_id)?'warning':'good')),
      node('p',{class:'change-label'},'ORIGINAL'),node('p',{},change.before),node('p',{class:'change-label'},'TAILORED'),node('p',{},change.after),
      node('p',{class:'change-reason'},change.reason),node('code',{},`Supporting facts: ${change.source_fact_ids.join(', ')}`)));
    const checks=content.pdf_checks;
    root.append(node('ul',{class:'pdf-checks'},...['Extractable text: passed','Contact retention: passed','Section reading order: passed','Expected text retention: passed','Text within page bounds: passed','Automatic visual layout review: not assessed'].map(text=>node('li',{},text))));
    root.append(node('div',{class:'studio-actions'},node('a',{class:'button primary',href:`/api/v1/artifacts/${generation.pdf_artifact_id}`,download:'tailored-resume.pdf'},'Download tailored PDF'),
      ...(generation.original_artifact_id ? [node('a',{class:'button secondary',href:`/api/v1/artifacts/${generation.original_artifact_id}`,download:'original-resume.pdf'},'Download original PDF')] : [])));
    let page=1;
    const image=node('img',{alt:`Generated resume page 1 of ${checks.pages}`,src:`/api/v1/resume-generations/${generation.id}/preview/1`});
    const label=node('span',{'aria-live':'polite'},`Page 1 of ${checks.pages}`);
    const before=button('Previous page',()=>showPage(page-1),'button secondary');
    const after=button('Next page',()=>showPage(page+1),'button secondary');
    function showPage(value) {page=value;image.src=`/api/v1/resume-generations/${generation.id}/preview/${page}`;image.alt=`Generated resume page ${page} of ${checks.pages}`;label.textContent=`Page ${page} of ${checks.pages}`;before.disabled=page===1;after.disabled=page===checks.pages;}
    image.addEventListener('error',()=>{label.textContent='Private preview unavailable. Reconnect or download the verified PDF.';});
    showPage(1);
    root.append(node('div',{class:'pdf-preview'},image,node('div',{class:'pdf-controls'},before,label,after)),node('p',{class:'generation-meta'},`PDF SHA-256: ${generation.pdf_sha256}`));
  }

  async function taskChanged(task,isNewTerminal) {
    if (!TASK_LABELS[task.kind]) return;
    const epoch=state.epoch;
    state.active.set(task.id,task);
    $('studio-progress').hidden=false;
    $('studio-progress').replaceChildren(node('strong',{},`${TASK_LABELS[task.kind]} · ${words(task.status)}`),
      node('progress',{max:100,value:task.progress,'aria-label':'Resume Studio task progress'},`${task.progress}%`),
      node('p',{},`${task.progress}% · ${words(task.current_step)} · attempt ${task.attempts} of ${task.max_attempts}`),
      ...(task.error_code ? [node('p',{class:'inline-warning'},guidance(task.error_code))] : []));
    if (isNewTerminal) {
      if (task.status==='SUCCEEDED') {
        if (task.kind==='resume_parse') await load({profileId:task.result.profile_version_id,restoreTasks:false});
        if (task.kind==='job_search') {
          const search=await request(`/api/v1/searches/${task.entity_id}`,{validate:'search'});
          if (epoch !== state.epoch || !connected() || search.profile_version_id !== state.profile?.id) return;
          state.search=search;state.changeRole=false;renderSearch();
        }
        if (task.kind==='jd_analysis') {
          const analysis=await chooseAnalysis(task.entity_id);
          if (!analysis) return;
          const search=await request(`/api/v1/searches/${analysis.search_id}`,{validate:'search'});
          if (epoch !== state.epoch || !connected() || analysis.id !== state.analysis?.id) return;
          state.search=search;renderSearch();
        }
        if (task.kind==='resume_generate') await load({generationId:task.entity_id,restoreTasks:false});
        notify(`${TASK_LABELS[task.kind]} complete. Review the saved result in Resume Studio.`,undefined,false,true);
      } else {
        notify(guidance(task.error_code),undefined,true);
        if (task.kind==='resume_generate') await load({generationId:task.entity_id,restoreTasks:false});
      }
    }
    actions();
  }

  function selectFile(file) {
    if (!file) return;
    $('profile-ai-consent').checked=false;
    state.file=null;
    if (file.size>5*1024*1024) {$('resume-file-state').textContent=GUIDANCE.PDF_TOO_LARGE;actions();return;}
    if (!file.name.toLowerCase().endsWith('.pdf')) {$('resume-file-state').textContent='Choose a PDF. The server also validates actual bytes.';actions();return;}
    state.file=file;$('resume-file-state').textContent=`${file.name} · ${(file.size/1024).toFixed(1)} KiB · ready for server validation`;actions();
  }
  $('resume-file').addEventListener('change',()=>selectFile($('resume-file').files[0]));
  for (const name of ['dragover','drop']) $('resume-drop').addEventListener(name,event=>event.preventDefault());
  $('resume-drop').addEventListener('dragenter',()=>$('resume-drop').classList.add('dragging'));
  $('resume-drop').addEventListener('dragleave',()=>$('resume-drop').classList.remove('dragging'));
  $('resume-drop').addEventListener('drop',event=>{$('resume-drop').classList.remove('dragging');if(!active('resume_parse'))selectFile(event.dataTransfer.files[0]);});
  $('profile-parsing-mode').addEventListener('change',()=>{$('profile-ai-consent').checked=false;actions();});
  $('profile-ai-consent').addEventListener('change',actions);
  $('resume-upload-form').addEventListener('submit',event=>{
    event.preventDefault();if (!state.file || active('resume_parse'))return;
    const mode=$('profile-parsing-mode').value;
    if (mode==='groq' && !$('profile-ai-consent').checked)return;
    const data=new FormData();data.append('resume',state.file);data.append('parsing_mode',mode);
    if (mode==='groq') {data.append('ai_consent','true');data.append('consent_version','groq-profile-v1');}
    notify('Uploading PDF for local validation…');mutate('/api/v1/profiles',data);
  });
  $('profile-version').addEventListener('change',()=>chooseProfile($('profile-version').value).catch(problem=>handle(problem,load)));
  $('new-fact-kind').replaceChildren(...KINDS.map(kind=>node('option',{value:kind,...(kind==='skills'?{selected:''}:{})},words(kind))));
  $('add-fact').addEventListener('click',()=>{
    const text=$('new-fact-text').value.trim();if (!text || !state.profile || !current()) return;
    const fact={id:crypto.randomUUID(),text,kind:$('new-fact-kind').value,source_ref:null};state.additions.push(fact);
    $('profile-facts').append(factEditor(fact,state.profile.facts.length+state.additions.length-1,true));$('new-fact-text').value='';markDirty();
  });
  $('discard-profile').addEventListener('click',()=>{state.dirty=false;state.additions=[];renderProfile();actions();});
  $('profile-edit-form').addEventListener('submit',event=>{
    event.preventDefault();let values;try {values=corrections();}catch{notify('Fact text cannot be blank. Correct it explicitly.',undefined,true);return;}
    if (!values.length) {state.dirty=false;actions();return;}
    mutate(`/api/v1/profiles/${state.profile.id}`,{expected_revision:state.profile.revision,corrections:values},'profile','PATCH',async profile=>{
      state.dirty=false;state.additions=[];state.profile=profile;state.analysis=null;state.search=null;$('job-analysis').hidden=true;$('tailoring-panel').hidden=true;$('groq-consent').checked=false;
      await load({profileId:profile.id,restoreTasks:false});notify('Corrections saved as a new unconfirmed profile version.');
    });
  });
  $('confirm-profile').addEventListener('click',()=>mutate(`/api/v1/profiles/${state.profile.id}/confirm`,{expected_revision:state.profile.revision},'profile','POST',async profile=>{state.profile=profile;await load({profileId:profile.id,restoreTasks:false});notify('Profile confirmed. Enter your preferred role to search.');}));
  $('matching-form').addEventListener('submit',event=>{
    event.preventDefault();if (!ready() || active('job_search'))return;
    const role=$('preferred-role').value.trim();if (role.length<2)return;
    state.analysis=null;$('groq-consent').checked=false;$('job-analysis').hidden=true;$('tailoring-panel').hidden=true;
    if (state.changeRole && state.search) mutate(`/api/v1/searches/${state.search.id}/decision`,{expected_revision:state.search.revision,decision:'change_role',preferred_title:role});
    else mutate('/api/v1/searches',{profile_version_id:state.profile.id,preferred_title:role,filters:{location:$('preferred-location').value.trim() || null,
      employment_type:$('preferred-type').value.trim() || null,remote:$('preferred-remote').value===''?null:$('preferred-remote').value==='true'}});
  });
  $('groq-consent').addEventListener('change',actions);
  $('generate-resume').addEventListener('click',()=>{if (!ready() || !state.analysis || !$('groq-consent').checked || active('resume_generate'))return;mutate('/api/v1/resume-generations',
    {analysis_id:state.analysis.id,profile_version_id:state.profile.id,consent:true,consent_version:'groq-resume-v2'});});
  $('generation-history').addEventListener('change',()=>chooseGeneration($('generation-history').value).catch(problem=>handle(problem,load)));
  $('reload-studio').addEventListener('click',()=>load());
  function reset() {
    state.epoch++;state.profile=null;state.profiles=[];state.search=null;state.analysis=null;state.generation=null;state.generations=[];
    state.active.clear();state.dirty=false;state.additions=[];state.file=null;state.pending=null;state.busy=false;
    $('resume-file').value='';$('resume-file-state').textContent='No file selected.';$('groq-consent').checked=false;
    $('profile-ai-consent').checked=false;$('profile-parsing-mode').value='local';$('profile-parsing-note').textContent='';
    for (const id of ['profile-review','job-analysis','tailoring-panel','studio-progress']) $(id).hidden=true;
    for (const id of ['profile-facts','profile-source','profile-links','generation-result','match-results','role-decision']) $(id).replaceChildren();
    $('profile-status').textContent='No profile loaded';renderVersionOptions();renderHistoryOptions();actions();
  }
  actions();
  return {load,taskChanged,reset};
}
