(() => {
  "use strict";
  let data = null, mode = "repair", original = null, currentOperation = null, order = [];
  const $ = (id) => document.getElementById(id);
  const pack = () => data.packs.find((item) => item.id === $("pack").value);
  const typeDef = () => data.types.find((item) => item.stored_type === $("type").value);
  const escapeHtml = (value) => { const node=document.createElement("span"); node.textContent=String(value??""); return node.innerHTML; };
  async function json(url, options) { const response=await fetch(url,options); const payload=await response.json(); if(!response.ok) throw new Error(payload.error||"Workbench request failed"); return payload; }

  function showReadiness(readiness) {
    data.readiness = readiness; const node=$("readiness");
    node.className=`state ${readiness.ready?"ready":"blocked"}`;
    node.innerHTML=`<strong>${escapeHtml(readiness.operator_state)}</strong>${readiness.reason?`<small>${escapeHtml(readiness.reason)}</small>`:""}`;
    updateFinalLabel();
  }
  async function refreshReadiness(){ try{showReadiness(await json("/api/question-workbench/readiness"));}catch(error){showReadiness({ready:false,operator_state:"Publishing unavailable — will save",reason:error.message});} }
  function updateFinalLabel(){
    if(!$('final-action')) return;
    const ready=data?.readiness?.ready;
    $("final-action").textContent=ready?(mode==="repair"?"Replace question & publish":"Add question & publish"):(mode==="repair"?"Save repair for publication":"Publishing unavailable — question will be saved");
  }
  function setMode(next){
    mode=next; original=null; currentOperation=null; $("editor").hidden=true; $("preview").hidden=true; $("search-results").replaceChildren();
    document.querySelectorAll("[data-mode]").forEach((button)=>button.classList.toggle("active",button.dataset.mode===mode));
    $("search-form").hidden=mode!=="repair"; $("chapter-wrap").hidden=mode!=="addition"; $("type-wrap").hidden=mode!=="addition";
    if(mode==="addition") openAddition(); refreshReadiness();
  }
  function fillSelectors(){
    $("pack").replaceChildren(...data.packs.map((item)=>new Option(`${item.title} · ${item.question_count} questions`,item.id)));
    $("type").replaceChildren(...data.types.map((item)=>new Option(`${item.label}${item.supported?"": " — legacy unsupported"}`,item.stored_type)));
    $("type").querySelectorAll("option").forEach((option)=>{const def=data.types.find((item)=>item.stored_type===option.value);option.disabled=!def.supported;});
    updateChapters();
  }
  function updateChapters(){ const selected=pack(); $("chapter").replaceChildren(...selected.chapters.map((item)=>new Option(`Chapter ${item.chapter}: ${item.chapter_title}`,JSON.stringify(item)))); }
  function preferredType(){ const packId=$("pack").value; const stored=new Set(); data.types.forEach((item)=>stored.add(item.stored_type)); return stored.has(packId==="fundamentals"?"mc":"multiple_choice")?(packId==="fundamentals"?"mc":"multiple_choice"):data.types.find((item)=>item.supported)?.stored_type; }
  function blankQuestion(){ const chapter=JSON.parse($("chapter").value); return {id:"",chapter:chapter.chapter,chapter_title:chapter.chapter_title,type:$("type").value,stem:"",choices:[{label:"A",text:""},{label:"B",text:""}],correct_answers:[],rationale:""}; }
  function openAddition(){ if(!data||!pack())return; $("type").value=preferredType(); openEditor(blankQuestion(),null); }

  function openEditor(question, source, operation=null){
    original=source?structuredClone(source):null; currentOperation=operation; $("editor").hidden=false; $("preview").hidden=true; $("final-action").disabled=false;
    $("editor-mode").textContent=mode==="repair"?"REPAIR EXISTING QUESTION":"ADD NEW QUESTION";
    $("question-id").textContent=question.id||"Permanent ID assigned atomically when saved";
    $("stem").value=question.stem||""; $("rationale").value=question.rationale||""; $("notes").value=typeof question.notes==="string"?question.notes:"";
    if(mode==="repair"){
      $("type").value=question.type; const chapters=pack().chapters; $("chapter").replaceChildren(...chapters.map((item)=>new Option(`Chapter ${item.chapter}: ${item.chapter_title}`,JSON.stringify(item))));
      $("chapter").value=JSON.stringify({chapter:question.chapter,chapter_title:question.chapter_title});
    }
    renderItems(question.choices||[]); order=[...(question.correct_answers||[])]; renderAnswers(); renderMeta(question); markChanges(); updateFinalLabel();
    $("editor").scrollIntoView({behavior:"smooth",block:"start"});
  }
  function renderMeta(question){
    const labels=[question.id||"ID reserved on save",pack()?.title,`Chapter ${question.chapter}: ${question.chapter_title}`,data.types.find((item)=>item.stored_type===question.type)?.label||question.type];
    $("record-meta").innerHTML=labels.map((item)=>`<span>${escapeHtml(item)}</span>`).join("");
  }
  function renderItems(items){
    $("items").replaceChildren(); items.forEach(addItem); const kind=typeDef()?.kind;
    $("items-section").hidden=kind==="text"; $("items-title").textContent=kind==="ordered"?"Response items":"Choices";
    $("answers-title").textContent=kind==="text"?"Accepted answers":kind==="ordered"?"Canonical correct sequence":"Correct answer";
  }
  function addItem(item={label:String.fromCharCode(65+$("items").children.length),text:""}){
    const row=document.createElement("div"); row.className="item-row";
    row.innerHTML=`<input class="item-label" maxlength="3" aria-label="Item label" value="${escapeHtml(item.label)}"><input class="item-text" aria-label="Item text" value="${escapeHtml(item.text)}"><button type="button" class="secondary">Remove</button>`;
    row.querySelector("button").onclick=()=>{row.remove();renderAnswers();markChanges();}; row.querySelectorAll("input").forEach((input)=>input.oninput=()=>{renderAnswers();markChanges();}); $("items").append(row);
  }
  function items(){ return [...document.querySelectorAll(".item-row")].map((row)=>({label:row.querySelector(".item-label").value.trim().toUpperCase(),text:row.querySelector(".item-text").value.trim()})); }
  function renderAnswers(){
    const target=$("answers"), definition=typeDef(); target.replaceChildren(); if(!definition)return;
    if(definition.kind==="text"){
      const area=document.createElement("textarea");area.id="accepted-answers";area.rows=3;area.placeholder="One accepted answer per line";area.value=order.join("\n");area.oninput=()=>{order=area.value.split("\n").map((x)=>x.trim()).filter(Boolean);markChanges();};target.className="text-answers";target.append(area);return;
    }
    target.className=""; const available=items().filter((item)=>item.label); const labels=new Set(available.map((item)=>item.label)); order=order.filter((label)=>labels.has(label));
    if(definition.kind==="ordered"){
      available.forEach((item)=>{if(!order.includes(item.label))order.push(item.label);});
      order.forEach((label,index)=>{const item=available.find((candidate)=>candidate.label===label);if(!item)return;const row=document.createElement("div");row.className="order-item";row.innerHTML=`<span><b>${escapeHtml(label)}</b> — ${escapeHtml(item.text)}</span><button type="button" class="secondary" aria-label="Move up">↑</button><button type="button" class="secondary" aria-label="Move down">↓</button>`;const buttons=row.querySelectorAll("button");buttons[0].disabled=index===0;buttons[1].disabled=index===order.length-1;buttons[0].onclick=()=>{[order[index-1],order[index]]=[order[index],order[index-1]];renderAnswers();markChanges();};buttons[1].onclick=()=>{[order[index+1],order[index]]=[order[index],order[index+1]];renderAnswers();markChanges();};target.append(row);});return;
    }
    available.forEach((item)=>{const label=document.createElement("label");label.className="answer-option";const input=document.createElement("input");input.type=definition.kind==="multiple_choice"?"checkbox":"radio";input.name="correct";input.value=item.label;input.checked=order.includes(item.label);input.onchange=()=>{order=[...target.querySelectorAll("input:checked")].map((node)=>node.value);markChanges();};label.append(input,document.createTextNode(`${item.label} — ${item.text}`));target.append(label);});
  }
  function collect(){
    const chapter=JSON.parse($("chapter").value); const question={id:currentOperation?.question_id||original?.id||"PENDING",chapter:chapter.chapter,chapter_title:chapter.chapter_title,type:$("type").value,stem:$("stem").value,choices:typeDef()?.kind==="text"?[]:items(),correct_answers:[...order],rationale:$("rationale").value};
    if($("notes").value.trim())question.notes=$("notes").value.trim(); return question;
  }
  function markChanges(){
    if(!original){document.querySelectorAll("#editor input,#editor textarea,#editor select").forEach((node)=>node.classList.remove("changed"));return;}
    let q;try{q=collect();}catch{return;} const fields={stem:$("stem"),rationale:$("rationale"),choices:$("items"),correct_answers:$("answers"),chapter:$("chapter"),type:$("type")};
    Object.entries(fields).forEach(([key,node])=>node.classList.toggle("changed",JSON.stringify(q[key])!==JSON.stringify(original[key])));
  }
  async function search(event){event.preventDefault();const results=$("search-results");results.textContent="Searching…";try{const response=await json(`/api/question-workbench/search?pack_id=${encodeURIComponent($("pack").value)}&q=${encodeURIComponent($("search").value)}`);results.replaceChildren();if(!response.results.length){results.textContent="No questions found.";return;}response.results.forEach((item)=>{const row=document.createElement("div");row.className="result";row.innerHTML=`<span><strong>${escapeHtml(item.question_id)} · Chapter ${escapeHtml(item.chapter)}</strong><small>${escapeHtml(item.stem)}</small></span>`;const button=document.createElement("button");button.type="button";button.className="secondary";button.textContent="Open complete record";button.onclick=()=>loadQuestion(item);row.append(button);results.append(row);});}catch(error){results.textContent=error.message;}}
  async function loadQuestion(item){try{const response=await json(`/api/question-workbench/question?pack_id=${encodeURIComponent(item.pack_id)}&question_id=${encodeURIComponent(item.question_id)}`);mode="repair";$("type").value=response.question.type;openEditor(response.question,response.question);}catch(error){$("search-results").textContent=error.message;}}
  async function preview(){try{const question=collect();renderPreview(question);$("validation").textContent="Canonical fields are ready for an interactive check.";$("validation").className="message ok";}catch(error){$("validation").textContent=error.message;}}
  function renderPreview(question){
    $("preview").hidden=false;$("preview-stem").textContent=question.stem;$("preview-answers").replaceChildren();$("preview-feedback").hidden=true;const definition=typeDef();
    if(definition.kind==="text"){const input=document.createElement("input");input.id="preview-text";input.placeholder="Type your answer";$("preview-answers").append(input);}
    else if(definition.kind==="ordered"){window.previewOrder=items().map((item)=>item.label);renderPreviewOrder(question);}
    else items().forEach((item)=>{const label=document.createElement("label");label.className="preview-choice";const input=document.createElement("input");input.type=definition.kind==="multiple_choice"?"checkbox":"radio";input.name="preview-answer";input.value=item.label;label.append(input,document.createTextNode(`${item.label}. ${item.text}`));$("preview-answers").append(label);});
    $("preview-submit").onclick=()=>gradePreview(question);$("preview").scrollIntoView({behavior:"smooth"});
  }
  function renderPreviewOrder(question){const target=$("preview-answers");target.replaceChildren();window.previewOrder.forEach((label,index)=>{const item=items().find((x)=>x.label===label);const row=document.createElement("div");row.className="order-item";row.innerHTML=`<span><b>${escapeHtml(label)}</b> — ${escapeHtml(item?.text)}</span><button class="secondary">↑</button><button class="secondary">↓</button>`;const buttons=row.querySelectorAll("button");buttons[0].disabled=index===0;buttons[1].disabled=index===window.previewOrder.length-1;buttons[0].onclick=()=>{[window.previewOrder[index-1],window.previewOrder[index]]=[window.previewOrder[index],window.previewOrder[index-1]];renderPreviewOrder(question);};buttons[1].onclick=()=>{[window.previewOrder[index+1],window.previewOrder[index]]=[window.previewOrder[index],window.previewOrder[index+1]];renderPreviewOrder(question);};target.append(row);});}
  async function gradePreview(question){let answer;if(typeDef().kind==="text")answer=$("preview-text").value;else if(typeDef().kind==="ordered")answer=window.previewOrder;else answer=[...document.querySelectorAll('[name="preview-answer"]:checked')].map((node)=>node.value);try{const result=await json("/api/question-workbench/grade",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question,answer})});const feedback=$("preview-feedback");feedback.hidden=false;feedback.innerHTML=`<strong>${result.is_correct?"Correct":"Incorrect"}</strong><p>Correct answer: ${escapeHtml(result.correct_answers.join(typeDef().kind==="ordered"?"":"; "))}</p><p>${escapeHtml(question.rationale)}</p>`;}catch(error){$("preview-feedback").hidden=false;$("preview-feedback").textContent=error.message;}}
  async function finalAction(){const button=$("final-action");button.disabled=true;button.textContent="Saving…";try{const response=await json("/api/question-workbench/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_id:currentOperation?.operation_id,operation_type:mode,pack_id:$("pack").value,question:collect()})});currentOperation=response.operation;$("question-id").textContent=currentOperation.question_id;showReadiness(response.readiness);$("save-state").textContent=currentOperation.state==="published"?`Published · ${response.publication.public_commit}`:"Saved for publication";$("validation").textContent=currentOperation.state==="published"?"Publication completed successfully.":"Saved durably. You can reopen this operation without losing its permanent ID.";$("validation").className="message ok";await reload();button.disabled=currentOperation.state==="published";}catch(error){$("validation").textContent=error.message;button.disabled=false;updateFinalLabel();}}
  function renderPending(){const target=$("pending");target.replaceChildren();if(!data.operations.length){target.textContent="No saved operations.";return;}data.operations.slice().reverse().forEach((op)=>{const card=document.createElement("article");card.className=`pending-card ${op.state==="published"?"published":""}`;card.innerHTML=`<div><strong>${op.operation_type==="repair"?"Repair":"Addition"} · ${escapeHtml(op.question_id)}</strong><p>${escapeHtml(op.question.stem.slice(0,120))}</p><small>${escapeHtml(op.pack_id)} · Chapter ${escapeHtml(op.question.chapter)} · ${escapeHtml(op.question.type)} · saved ${escapeHtml(op.updated_at)}${op.blocker?` · ${escapeHtml(op.blocker)}`:""}</small></div>`;const actions=document.createElement("div");actions.className="pending-actions";const edit=document.createElement("button");edit.className="secondary";edit.textContent=op.state==="published"?"Published":op.state==="publishing"?"Publication recovery pending":"Reopen and edit";edit.disabled=op.state!=="pending";edit.onclick=()=>reopen(op);actions.append(edit);if(op.state!=="published"&&(data.readiness.ready||op.state==="publishing")){const publish=document.createElement("button");publish.textContent=op.state==="publishing"?"Resume publication":op.operation_type==="repair"?"Replace question & publish":"Add question & publish";publish.onclick=()=>publishPending(op,publish);actions.append(publish);}card.append(actions);target.append(card);});}
  function reopen(op){mode=op.operation_type;document.querySelectorAll("[data-mode]").forEach((button)=>button.classList.toggle("active",button.dataset.mode===mode));$("pack").value=op.pack_id;updateChapters();$("chapter").value=JSON.stringify({chapter:op.question.chapter,chapter_title:op.question.chapter_title});$("type").value=op.question.type;$("search-form").hidden=mode!=="repair";$("chapter-wrap").hidden=mode!=="addition";$("type-wrap").hidden=mode!=="addition";openEditor(op.question,op.original_question,op);}
  async function publishPending(op,button){button.disabled=true;button.textContent="Publishing…";try{const response=await json("/api/question-workbench/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_id:op.operation_id})});showReadiness(response.readiness);await reload();}catch(error){button.disabled=false;button.textContent="Try publication again";alert(error.message);}}
  async function reload(){const response=await json("/api/question-workbench");data=response;showReadiness(data.readiness);renderPending();}
  async function init(){data=await json("/api/question-workbench");fillSelectors();showReadiness(data.readiness);renderPending();setMode("repair");}
  document.querySelectorAll("[data-mode]").forEach((button)=>button.onclick=()=>setMode(button.dataset.mode));$("pack").onchange=()=>{updateChapters();if(mode==="addition")openAddition();refreshReadiness();};$("chapter").onchange=()=>{if(mode==="addition"&&!currentOperation)openAddition();renderMeta(collect());markChanges();refreshReadiness();};$("type").onchange=()=>{order=[];renderItems(typeDef().kind==="text"?[]:items().length?items():[{label:"A",text:""},{label:"B",text:""}]);renderAnswers();renderMeta(collect());markChanges();refreshReadiness();};$("search-form").onsubmit=search;$("add-item").onclick=()=>{addItem();renderAnswers();};$("stem").oninput=$("rationale").oninput=$("notes").oninput=markChanges;$("preview-button").onclick=preview;$("back-to-edit").onclick=()=>{$("preview").hidden=true;$("editor").scrollIntoView({behavior:"smooth"});};$("final-action").onclick=finalAction;$("refresh").onclick=reload;
  init().catch((error)=>{document.body.innerHTML=`<main><section class="panel"><h1>Workbench unavailable</h1><p>${escapeHtml(error.message)}</p></section></main>`;});
})();
