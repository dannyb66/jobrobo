/* Static local review overlay. Submission history is reporting, never a gate. */
(() => {
  const data = window.JOBROBO_SUBMIT_HISTORY;
  const script = document.currentScript;
  if (!data || document.querySelector('#submission-filter')) return;
  const roles = [...document.querySelectorAll('article.role')];
  const labels = {applied:'Submitted', submission_uncertain:'Uncertain', submitting:'Submitting',
    duplicate:'Duplicate / reserved', awaiting_manual_submit:'Awaiting manual Submit',
    awaiting_correction:'Needs correction', awaiting_review:'Awaiting review', not_started:'Not started'};
  const canonical = value => {
    const u = new URL(value); u.hash = '';
    u.pathname = u.pathname.replace(/\/$/, '');
    if (['jobs.ashbyhq.com','jobs.lever.co'].includes(u.hostname)) {
      u.pathname = u.pathname.replace(/\/(application|apply|thanks|thank-you)$/, ''); u.search = '';
    } else {
      for (const k of [...u.searchParams.keys()])
        if (k.toLowerCase().startsWith('utm_') || ['source','gh_src','lever-source'].includes(k.toLowerCase())) u.searchParams.delete(k);
      u.searchParams.sort();
    }
    return u.href.replace(/\/$/, '');
  };
  const link = (text, url) => {
    const a = document.createElement('a'); a.textContent = text;
    if (new URL(url).protocol === 'file:') a.href = url;
    return a;
  };
  const label = document.createElement('label'); label.textContent = 'Application status';
  const select = document.createElement('select'); select.id = 'submission-filter';
  for (const [value,text] of [['remaining','Hide submitted / uncertain'],['all','All statuses'],['submitted','Submitted / duplicate'],['uncertain','Uncertain / submitting'],['manual','Awaiting manual review'],['not_started','No previous run'],['other','Other attempted outcomes']]) {
    const o = document.createElement('option'); o.value = value; o.textContent = text; select.append(o);
  }
  for (const state of [...new Set(Object.values(data.by_url).flatMap(h=>h.statuses))].sort()) {
    const o = document.createElement('option'); o.value = 'status:'+state;
    o.textContent = 'Status: '+(labels[state] || state.replaceAll('_',' ')); select.append(o);
  }
  label.append(select); document.querySelector('.filters')?.append(label);
  const note = document.createElement('p'); note.className = 'note';
  note.append('Submission history saved '+data.generated_at+'. Reload this page after a run update. ', link('All submit runs', data.runs_url), ' · ', link('Remaining jobs JSON', script.dataset.remaining), ' · ', link('Remaining jobs TXT', script.dataset.remainingUrls));
  if (data.warnings?.length) note.append(' Some run files could not be refreshed; inspect the run dashboard.');
  document.querySelector('.filters')?.before(note);
  for (const role of roles) {
    const posting = role.querySelector('h3 a[href]');
    const history = posting && data.by_url[canonical(posting.href)];
    role._submissionHistory = history;
    const p = document.createElement('p');
    const strong = document.createElement('strong'); strong.textContent = 'Application: '+(labels[history?.status || 'not_started'] || history.status.replaceAll('_', ' '));
    p.append(strong); role.querySelector('div')?.append(p);
    if (!history) continue;
    const detail = document.createElement('details'); const summary = document.createElement('summary');
    summary.textContent = 'Submission runs ('+history.attempts.length+')'; detail.append(summary);
    const list = document.createElement('ul');
    for (const attempt of history.attempts) {
      const item = document.createElement('li');
      item.append((labels[attempt.status] || attempt.status.replaceAll('_',' '))+' · ',link(attempt.run_id, attempt.progress_url),' · '+(attempt.updated_at || 'time unavailable'));
      if (['submission_uncertain','submitting'].includes(attempt.status)) item.append(' · ',link('Inspect uncertain outcome', attempt.review_url));
      if (attempt.report_url) item.append(' · ',link('Report', attempt.report_url));
      list.append(item);
    }
    detail.append(list); role.append(detail);
  }
  const apply = () => {
    if (typeof window.filter === 'function') window.filter();
    const mode = select.value;
    for (const role of roles) {
      const h = role._submissionHistory, state = h?.status || 'not_started';
      const match = mode === 'all' || mode === 'remaining' && !h?.exclude_from_remaining ||
        mode.startsWith('status:') && h?.statuses.includes(mode.slice(7)) ||
        mode === 'submitted' && ['applied','duplicate'].includes(state) ||
        mode === 'uncertain' && h?.has_uncertain_attempts ||
        mode === 'manual' && h?.statuses.some(s=>['awaiting_manual_submit','awaiting_correction','awaiting_review'].includes(s)) ||
        mode === 'not_started' && !h ||
        mode === 'other' && h && !['applied','duplicate','submission_uncertain','submitting','awaiting_manual_submit','awaiting_correction','awaiting_review','pending'].includes(state);
      role.hidden ||= !match;
    }
    for (const group of document.querySelectorAll('[data-group]')) group.hidden = ![...group.querySelectorAll('.role')].some(r=>!r.hidden);
    document.querySelector('#count').textContent = 'Showing '+roles.filter(r=>!r.hidden).length+' of '+roles.length+' engineering roles';
  };
  document.querySelectorAll('input,select').forEach(c=>c.addEventListener('input',apply));
  apply();
})();
