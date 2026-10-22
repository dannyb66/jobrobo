/* Default preparation guard. Submit runner opts into a separate literal mode. */
(() => {
  const kernelSolver = false;
  const solverFrame = window!==window.top &&
    ((/(^|\.)(google\.com|recaptcha\.net)$/.test(location.hostname)&&location.pathname.startsWith('/recaptcha/'))||
     /(^|\.)(hcaptcha\.com|challenges\.cloudflare\.com|arkoselabs\.com|funcaptcha\.com|geetest\.com)$/.test(location.hostname));
  if(kernelSolver && solverFrame)return; // Solver UI is distinct from the employer's final form.
  if (window.__jobroboPrepare) return;
  const submissionMode = false;
  const state = window.__jobroboPrepare = {blocked: [], actions: []};
  state.submissionMode = submissionMode;
  state.documentId = crypto.randomUUID?.() || String(Date.now())+'-'+String(Math.random());
  state.finalActivated = false;
  // Manual handoff permits trusted browser input. It never clicks a control.
  state.manualHandoff = window.__jobroboManualConfig || null;
  state.manualEvent = (event, extra={}) => {
    if (!state.manualHandoff) return;
    const key='jobrobo.manual.'+state.manualHandoff.token;
    let saved; try {saved=JSON.parse(sessionStorage.getItem(key)||'null')} catch {}
    saved=saved||{token:state.manualHandoff.token,activations:0};
    if(event==='activation')saved.activations++;
    Object.assign(saved,{event,url:location.href,at:Date.now()},extra);
    state.manualRecord=saved;
    try {sessionStorage.setItem(key,JSON.stringify(saved))} catch {}
    try {window.jobroboManualEvent?.(JSON.stringify(saved))} catch {}
  };
  state.handoffManual = config => {
    if(!submissionMode)return false;
    window.__jobroboManualConfig=config;state.manualHandoff=config;
    state.manualEvent('handoff');return true;
  };
  const submitBinding = button => JSON.stringify({
    button: [button.type,button.textContent,button.getAttribute('aria-label')],
    fields: [...(button.form||document).querySelectorAll('input,textarea,select,[role=combobox],[role=radio],[role=checkbox]')].map(e=>[
      e.name,e.id,e.type,e.value,e.checked,e.required,e.disabled,e.getAttribute('aria-checked'),e.getAttribute('data-value'),
      [...(e.files||[])].map(f=>[f.name,f.size,f.lastModified]),[...(e.options||[])].map(o=>[o.value,o.selected])]),
    jd: [...document.querySelectorAll('script[type="application/ld+json"]')].map(e=>e.textContent)
  });
  state.armSubmit = button => {
    if (!submissionMode || state.finalActivated || !button?.isConnected) return false;
    state.finalControl = button; state.finalBinding = submitBinding(button); return true;
  };
  state.disarmSubmit = () => {
    state.finalControl = null; state.allowedForm = null;
    return {disarmed: true, activated: state.finalActivated};
  };
  document.addEventListener('input', () => {state.finalControl=null}, true);
  // Text changes already emit input. Their delayed blur/change can occur
  // inside the validated Submit click's focus transition, before click fires.
  document.addEventListener('change', e => {
    if(e.target.type==='file'||state.finalControl&&submitBinding(state.finalControl)!==state.finalBinding)state.finalControl=null;
  }, true);
  new MutationObserver(changes=>{
    if(changes.some(change=>(change.target.nodeType===1?change.target:change.target.parentElement)?.closest('script[type="application/ld+json"]')))
      state.finalControl=null;
  }).observe(document,{subtree:true,childList:true,characterData:true});
  const text = e => (e.innerText || e.textContent || e.value || e.getAttribute('aria-label') || '').trim();
  const next = /^(next|continue|review|review application|save and continue|continue application)(\s*[→›»])?$/i;
  const final = /submit|send application|finish|complete application|apply now|^apply$/i;
  state.captureUpload = e => {
    if (e.target !== state.uploadControl || e.target.type !== 'file') return;
    state.uploads = [...e.target.files].map(file => {
      const record = {name: file.name, size: file.size, pending: true};
      file.arrayBuffer().then(bytes => crypto.subtle.digest('SHA-256', bytes)).then(hash => {
        record.sha256 = [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2,'0')).join(''); record.pending = false;
      }).catch(() => { record.pending = false; record.error = 'hash_failed'; });
      return record;
    });
  };
  document.addEventListener('change', state.captureUpload, true);
  document.addEventListener('submit', e => {
    if(submissionMode && state.manualHandoff && state.manualPermit && e.isTrusted){
      state.manualPermit=false;state.actions.push('manual-submit-event');return;
    }
    if (submissionMode && state.finalActivated && state.allowedForm === e.target) {
      state.allowedForm = null; state.actions.push('final-submit-event'); return;
    }
    if (e.submitter && e.submitter === state.nextControl && next.test(text(e.submitter))) {
      // Permit the site's client-side Next handler, never native form POST.
      e.preventDefault(); state.nextControl = null; state.actions.push('next-handler'); return;
    }
    e.preventDefault(); e.stopImmediatePropagation(); state.blocked.push('submit-event');
  }, true);
  document.addEventListener('keydown', e => {
    if(submissionMode && state.manualHandoff && e.isTrusted && e.key==='Enter' && e.target.tagName!=='TEXTAREA'){
      state.manualPermit=true;state.manualEvent('activation');return;
    }
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault(); e.stopImmediatePropagation(); state.blocked.push('enter');
    }
  }, true);
  document.addEventListener('click', e => {
    const b = e.composedPath().find(n => n.matches?.('button,input[type=submit],input[type=image],[role=button]'));
    if(submissionMode && state.manualHandoff && e.isTrusted && b &&
       (final.test(text(b)) || b.type==='submit')){
      state.manualPermit=true;
      if(!next.test(text(b)))state.manualEvent('activation');
      setTimeout(()=>{state.manualPermit=false},1000);return;
    }
    if (submissionMode && b && b === state.finalControl && !state.finalActivated && submitBinding(b)===state.finalBinding) {
      state.finalControl=null; state.finalActivated=true; state.allowedForm=b.form;
      state.actions.push('final-activation');
      setTimeout(()=>{state.allowedForm=null},1000); return;
    }
    if (b && b === state.choiceControl && b.matches('button[aria-pressed][data-option]') && /^(yes|no)$/.test(b.dataset.option)) {
      e.preventDefault(); state.choiceControl = null; state.actions.push('choice-handler'); return;
    }
    if (b && b === state.openControl && b.type !== 'submit') { state.openControl = null; return; }
    if (b && (final.test(text(b)) || (b.type === 'submit' && !next.test(text(b))))) {
      e.preventDefault(); e.stopImmediatePropagation(); state.blocked.push('final-click');
    }
  }, true);
  // Block both native methods, which otherwise bypass the submit event.
  const nativeSubmit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function() {
    if(submissionMode && state.manualHandoff && state.manualPermit){state.manualPermit=false;return nativeSubmit.call(this);}
    if (submissionMode && state.finalActivated && state.allowedForm === this) {
      state.allowedForm=null; return nativeSubmit.call(this);
    }
    state.blocked.push('form.submit');
  };
  const requestSubmit = HTMLFormElement.prototype.requestSubmit;
  HTMLFormElement.prototype.requestSubmit = function(submitter) {
    if(submissionMode && state.manualHandoff && state.manualPermit)return requestSubmit.call(this,submitter);
    if (submissionMode && state.finalActivated && state.allowedForm === this) return requestSubmit.call(this, submitter);
    if (submitter && submitter === state.nextControl && next.test(text(submitter))) return requestSubmit.call(this, submitter);
    state.blocked.push('form.requestSubmit');
  };
})();
