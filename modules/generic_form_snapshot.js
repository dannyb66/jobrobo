const roots = [document];
for (let i=0;i<roots.length;i++) for (const e of roots[i].querySelectorAll('*')) if(e.shadowRoot) roots.push(e.shadowRoot);
const all = selector => roots.flatMap(r => [...r.querySelectorAll(selector)]);
const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[aria-hidden=true]');
const clean = e => {if(!e)return '';const c=e.cloneNode(true);c.querySelectorAll('input,textarea,select,button,script,style,[role=listbox],.dropdown-container,.dropdown-results,.ashby-application-form-autocomplete-options').forEach(x=>x.remove());return (c.textContent||'').trim();};
const labelled = e => (e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>clean(e.getRootNode().getElementById?.(id)||document.getElementById(id))).join(' ').trim();
const label = e => e.getAttribute('aria-label') || labelled(e) || [...(e.labels||[])].map(clean).join(' ') || clean(e.closest('.field,.application-question,[data-field-path]')?.querySelector('.application-label,label,[data-question-label]')) || e.placeholder || e.name || e.id || '';
const groups = new Map();
const forms=all('form');
const formKey=e=>{const f=e.form||e.closest('form');return f?(f.id?'id:'+f.id:'index:'+forms.indexOf(f)):'';};
const fieldSelector='input,textarea,select,[role=combobox],[role=checkbox],[role=radio],[role=textbox],[contenteditable=true],button[aria-pressed][data-option]';
const fields = all(fieldSelector+',[aria-required=true]')
.filter((e,i,a)=>a.indexOf(e)===i && !(e.matches('input') && e.closest('[role=combobox]') && e.closest('[role=combobox]')!==e)
 && !(!e.matches('input,textarea,select,[role=combobox],[role=checkbox],[role=radio]')&&e.querySelector(fieldSelector)))
.map(e=>{
 const container=e.closest('fieldset,[role=radiogroup],.application-question,.field,[data-field-path]');
 if(container&&!groups.has(container))groups.set(container,'group-'+groups.size);
 const booleanButton=e.matches('button[aria-pressed][data-option]')&&['yes','no'].includes(e.dataset.option)&&!!e.closest('[data-field-path]');
 const role=booleanButton?'radio':e.getAttribute('role');
 const type=booleanButton?'radio':e.type||(role==='textbox'||e.isContentEditable?(e.getAttribute('aria-multiline')==='true'?'textarea':'text'):role||'unsupported'), choice=['radio','checkbox'].includes(type);
 const header=container?.querySelector('legend,[data-question-label],.application-label,h3,h4,:scope > label');
 const requiredLabel=e.closest('[data-field-path]')?.querySelector(':scope > label');
 const wrapper=container?.parentElement;
 const isolated=wrapper&&![...wrapper.querySelectorAll(fieldSelector)].some(c=>!container.contains(c));
 const outerHeader=isolated?[...wrapper.children].find(c=>c!==container&&/^(P|LABEL|H[1-6]|LEGEND)$/.test(c.tagName)&&clean(c)):null;
 const cardTitle=container?.closest('[data-qa=additional-cards]')?.querySelector('[data-qa=card-name]');
 let ownReference=labelled(e), ownLabel=[...(e.labels||[])].map(clean).join(' ').trim();
 if(ownLabel&&ownReference.endsWith(ownLabel))ownReference=ownReference.slice(0,-ownLabel.length).trim();
 let question=choice ? (labelled(container||e)||clean(header)||clean(outerHeader)||ownReference||label(e)) : label(e);
 if(choice&&cardTitle&&/how did you hear/i.test(clean(cardTitle))) question=clean(cardTitle)+' '+question;
 const groupChoice=type==='checkbox'&&!!container&&container.querySelectorAll('input[type=checkbox],[role=checkbox]').length>1;
 const required=!!e.required||e.getAttribute('aria-required')==='true'||/[*✱]/.test(question)||choice&&container?.getAttribute('aria-required')==='true'||!!requiredLabel&&/(?:^|[_\s-])required(?:[_\s-]|$)/i.test(requiredLabel.className);
 const locationWidget=e.matches('input.location-input')&&!!e.parentElement?.querySelector('.dropdown-results');
 const combo=e.getAttribute('role')==='combobox'||e.getAttribute('aria-autocomplete')==='list'||e.getAttribute('aria-haspopup')==='listbox'||locationWidget;
 const selectedNode=combo?e.closest('[class*="select__control"],[class*="-control"]')?.querySelector('[class*="single-value"],[class*="singleValue"]'):null;
 const selectedText=e.getAttribute('aria-valuetext')||clean(selectedNode);
 const committed=locationWidget?!!e.parentElement?.querySelector('input[name=selectedLocation]')?.value:!!selectedText||!!e.getAttribute('data-value')||combo&&e.tagName!=='INPUT'&&!/^(select|choose)(\b|\.{2,})/i.test(clean(e));
 const selectedCountryCode=[...(selectedNode?.querySelector('.iti__flag')?.classList||[])].find(c=>/^iti__[a-z]{2}$/.test(c))||'';
 const value=selectedText||(combo&&e.tagName!=='INPUT'?(e.getAttribute('data-value')||clean(e)):(e.isContentEditable?e.innerText:e.value||''));
 return {element:e,tag:e.tagName.toLowerCase(),type:combo?'text':type,name:role==='radio'&&container?groups.get(container):e.name||e.id||question,id:e.id||'',
 form_id:formKey(e)||'default',form_key:formKey(e),label:label(e),question,option_label:booleanButton?clean(e):label(e),group:choice&&container?groups.get(container):'',
 context_text:clean(container&&isolated?wrapper:e.closest('.application-question,.field')||e.parentElement?.parentElement).slice(0,1600),display_text:clean(e).slice(0,2000),
 required,native_required:!!e.required,control_required:groupChoice?false:required,group_required:groupChoice&&required||choice&&!!header&&/[*✱]/.test(clean(header)),
 visible:visible(e),disabled:!!e.disabled,readonly:!!e.readOnly,combobox:combo,location_widget:locationWidget,committed:!!committed,
 checked:e.checked??(e.getAttribute('aria-checked')==='true'||booleanButton&&e.getAttribute('aria-pressed')==='true'),value,selected_country_code:selectedCountryCode,boolean_button:booleanButton,
 valid:locationWidget&&required&&!committed?false:combo&&required&&/^(select|choose)(\b|\.{2,})/i.test(value)?false:groupChoice?true:e.validity?e.validity.valid:true,multiple:!!e.multiple,max_length:e.maxLength>0?e.maxLength:null,
 min:e.min||'',max:e.max||'',options:e.options?[...e.options].map(o=>({label:o.text.trim(),value:o.value,selected:o.selected,disabled:o.disabled})):[],
 files:[...(e.files||[])].map(f=>({name:f.name,size:f.size}))};
});
// Required visible custom widgets with only hidden native proxies must block
// preparation until a supported, visibly selected answer can be established.
for(const wrapper of all('[data-field-path]')){
 const heading=wrapper.querySelector(':scope > label');
 if(!visible(wrapper)||!heading||!/(?:^|[_\s-])required(?:[_\s-]|$)/i.test(heading.className)||fields.some(f=>wrapper.contains(f.element)&&f.visible))continue;
 const question=clean(heading);
 fields.push({element:wrapper,tag:'div',type:'unsupported',name:wrapper.dataset.fieldPath,question,label:question,form_key:formKey(wrapper),form_id:formKey(wrapper)||'default',required:true,visible:true,valid:false,value:'',checked:false,options:[],files:[...wrapper.querySelectorAll('input[type=file]')].flatMap(e=>[...(e.files||[])].map(f=>({name:f.name,size:f.size}))),display_text:clean(wrapper)});
}
const buttons=all('button,input[type=submit],a,[role=button]').filter(e=>visible(e)&&!e.disabled).map(e=>({element:e,text:(e.innerText||e.textContent||e.value||e.getAttribute('aria-label')||'').trim(),type:e.type||'',href:e.href||'',tag:e.tagName.toLowerCase(),form_key:formKey(e)}));
const text=(document.body?.innerText||'');
const file_receipts=all('span,div,p,a').filter(visible).map(e=>(e.innerText||'').trim()).filter(t=>t.length<180&&/\.pdf$/i.test(t));
let job=null;
const visit=x=>{if(!x||typeof x!=='object')return;if(x['@type']==='JobPosting')job=x;for(const v of Object.values(x))if(Array.isArray(v))v.forEach(visit);else if(v&&typeof v==='object')visit(v);};
for(const script of document.querySelectorAll('script[type="application/ld+json"]'))try{visit(JSON.parse(script.textContent));}catch{}
const description=document.querySelector('[itemprop=description],.job-sections,.posting-page .content,.posting-page,.posting-description,#content .content-intro,.job__description,.job-description,[data-testid=job-description],.ashby-job-posting-description,main');
return {url:location.href,title:document.title,site_name:document.querySelector('meta[property="og:site_name"]')?.content||'',location:document.querySelector('.job__location,.job-location,[data-testid=job-location],.location')?.innerText||'',fields,buttons,text:text.slice(0,70000),job,file_receipts,frame_count:all('iframe,frame').filter(visible).length,
 forms:forms.filter(visible).map(f=>({method:f.method,action_path:new URL(f.action||location.href,location.href).pathname})),
 parser_busy:all('[aria-busy=true],[role=status]').some(e=>visible(e)&&/pars(?:e|ing)|autofill|processing resume/i.test(e.innerText||e.getAttribute('aria-label')||'')),
 alerts:all('[role=alert],[aria-live=assertive]').filter(visible).map(e=>e.innerText.trim()).filter(Boolean),
 description:description?.innerText||'',headings:all('__JOBROBO_CONFIRMATION_SELECTOR__').filter(visible).map(e=>e.innerText.trim()),
 application_success:all('__JOBROBO_APPLICATION_SUCCESS_SELECTOR__').filter(visible).map(e=>e.innerText.trim()).filter(Boolean),
 challenge:all('iframe').some(e=>visible(e)&&e.getBoundingClientRect().height>100&&/captcha|challenge/i.test((e.src||'')+' '+e.title)),
 guard:window.__jobroboPrepare?{blocked:window.__jobroboPrepare.blocked,actions:window.__jobroboPrepare.actions,uploads:window.__jobroboPrepare.uploads||[]}:null};
