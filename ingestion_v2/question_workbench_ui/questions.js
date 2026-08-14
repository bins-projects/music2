(() => {
  "use strict";
  const BROWSE_STATE_KEY = "prepflow.questionWorkbench.browse.v1";
  let data = null, mode = "repair", original = null, currentOperation = null, order = [], browseRequest = 0;
  let browseState = {
    packId: "", chapter: "", query: "", page: 1, pageSize: 40,
    scrollY: 0, response: null, currentIndex: -1, currentQuestion: null,
  };
  const $ = (id) => document.getElementById(id);
  const pack = () => data.packs.find((item) => item.id === $("pack").value);
  const typeDef = () => data.types.find((item) => item.stored_type === $("type").value);
  const typeLabel = (stored) => data.types.find((item) => item.stored_type === stored)?.label || String(stored || "Unknown");
  const escapeHtml = (value) => { const node=document.createElement("span"); node.textContent=String(value??""); return node.innerHTML; };
  async function json(url, options) { const response=await fetch(url,options); const payload=await response.json(); if(!response.ok) throw new Error(payload.error||"Workbench request failed"); return payload; }
  function restoreBrowseState(){
    try {
      const saved=JSON.parse(sessionStorage.getItem(BROWSE_STATE_KEY)||"null");
      if(saved&&typeof saved==="object") browseState={...browseState,...saved,response:null,currentIndex:-1,currentQuestion:null};
    } catch { sessionStorage.removeItem(BROWSE_STATE_KEY); }
  }
  function persistBrowseState(){
    const {packId,chapter,query,page,pageSize,scrollY}=browseState;
    sessionStorage.setItem(BROWSE_STATE_KEY,JSON.stringify({packId,chapter,query,page,pageSize,scrollY}));
  }

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
    mode=next; original=null; currentOperation=null;
    $("editor").hidden=true; $("preview").hidden=true; $("record-view").hidden=true;
    document.querySelectorAll("[data-mode]").forEach((button)=>button.classList.toggle("active",button.dataset.mode===mode));
    $("search-form").hidden=mode!=="repair"; $("chapter-wrap").hidden=false; $("type-wrap").hidden=mode!=="addition";
    updateChapters();
    if(mode==="addition") openAddition();
    else {
      $("search").value=browseState.query;
      void browseQuestions(browseState.page,true);
    }
    refreshReadiness();
  }
  function fillSelectors(){
    $("pack").replaceChildren(...data.packs.map((item)=>new Option(`${item.title} · ${item.question_count} questions`,item.id)));
    if(data.packs.some((item)=>item.id===browseState.packId)) $("pack").value=browseState.packId;
    browseState.packId=$("pack").value;
    $("type").replaceChildren(...data.types.map((item)=>new Option(`${item.label}${item.supported?"": " — legacy unsupported"}`,item.stored_type)));
    $("type").querySelectorAll("option").forEach((option)=>{const def=data.types.find((item)=>item.stored_type===option.value);option.disabled=!def.supported;option.hidden=option.value==="multiple_choice";});
    updateChapters();
  }
  function updateChapters(){
    const selected=pack(); if(!selected)return;
    const options=selected.chapters.map((item)=>new Option(`Chapter ${item.chapter}: ${item.chapter_title}`,mode==="repair"?String(item.chapter):JSON.stringify(item)));
    if(mode==="repair") options.unshift(new Option("All chapters",""));
    $("chapter").replaceChildren(...options);
    if(mode==="repair"&&selected.chapters.some((item)=>String(item.chapter)===String(browseState.chapter))) $("chapter").value=String(browseState.chapter);
  }
  function preferredType(){ return "mc"; }
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
  function search(event){event.preventDefault();browseState.query=$("search").value.trim();browseState.page=1;void browseQuestions(1,false);}
  async function browseQuestions(page=1,restoreScroll=false){
    const results=$("search-results"); results.textContent="Loading questions…";
    browseState.packId=$("pack").value; browseState.chapter=$("chapter").value; browseState.query=$("search").value.trim();
    const params=new URLSearchParams({pack_id:browseState.packId,q:browseState.query,chapter:browseState.chapter,page:String(page),page_size:String(browseState.pageSize)});
    const request=++browseRequest;
    try{
      const response=await json(`/api/question-workbench/search?${params}`);
      if(request!==browseRequest)return;
      browseState.response=response; browseState.page=response.page; persistBrowseState(); renderBrowseResults();
      if(restoreScroll) requestAnimationFrame(()=>window.scrollTo({top:browseState.scrollY,behavior:"instant"}));
    }catch(error){results.textContent=error.message;}
  }
  function renderBrowseResults(){
    const target=$("search-results"), response=browseState.response; target.replaceChildren();
    if(!response)return;
    const heading=document.createElement("div"); heading.className="results-heading";
    heading.innerHTML=`<strong>${response.total.toLocaleString()} ${response.total===1?"question":"questions"}</strong><span>Page ${response.page} of ${response.total_pages}</span>`;
    target.append(heading);
    if(!response.results.length){const empty=document.createElement("p");empty.textContent="No questions found in this Pack and chapter scope.";target.append(empty);return;}
    response.results.forEach((item,index)=>{
      const row=document.createElement("button"); row.type="button"; row.className="result";
      row.innerHTML=`<span class="result-reference">${escapeHtml(item.reference)}</span><span class="result-facts">Chapter ${escapeHtml(item.chapter)} · ${escapeHtml(typeLabel(item.type))}</span><span class="result-stem">${escapeHtml(item.stem)}</span>`;
      row.onclick=()=>loadQuestion(item,true,index); target.append(row);
    });
    const pagination=document.createElement("div");pagination.className="pagination";
    const previous=document.createElement("button");previous.type="button";previous.className="secondary";previous.textContent="Previous page";previous.disabled=!response.has_previous;previous.onclick=()=>{browseState.scrollY=0;void browseQuestions(response.page-1,false);};
    const next=document.createElement("button");next.type="button";next.className="secondary";next.textContent="Next page";next.disabled=!response.has_next;next.onclick=()=>{browseState.scrollY=0;void browseQuestions(response.page+1,false);};
    pagination.append(previous,next);target.append(pagination);
  }
  async function loadQuestion(item,rememberScroll=true,index=null){
    try{
      if(rememberScroll){browseState.scrollY=window.scrollY;persistBrowseState();}
      const response=await json(`/api/question-workbench/question?pack_id=${encodeURIComponent(item.pack_id)}&question_id=${encodeURIComponent(item.question_id)}`);
      browseState.currentQuestion=response.question;
      browseState.currentIndex=index??browseState.response.results.findIndex((candidate)=>candidate.question_id===item.question_id);
      renderRecordView(response.question,item);
    }catch(error){$("search-results").textContent=error.message;}
  }
  function renderRecordView(question,item){
    $("editor").hidden=true;$("preview").hidden=true;$("record-view").hidden=false;
    const absolute=(browseState.page-1)*browseState.pageSize+browseState.currentIndex+1;
    const scope=browseState.chapter?`Chapter ${browseState.chapter}`:"All chapters";
    $("record-position").textContent=`Question ${absolute} of ${browseState.response.total} in ${scope}`;
    $("previous-question").disabled=absolute<=1;$("next-question").disabled=absolute>=browseState.response.total;
    const reference=item.reference||"Reference unavailable";
    $("browse-record-meta").innerHTML=[reference,question.id||"Reference unavailable",`Chapter ${question.chapter}: ${question.chapter_title}`,typeLabel(question.type||question.question_type)].map((value)=>`<span>${escapeHtml(value)}</span>`).join("");
    $("browse-record-stem").textContent=question.stem||"";
    const choices=(question.choices||[]).map((choice)=>`<li><b>${escapeHtml(choice.label)}</b> — ${escapeHtml(choice.text)}</li>`).join("");
    const choiceSection=choices?`<section><h3>Choices / response items</h3><ol>${choices}</ol></section>`:"";
    const notes=typeof question.notes==="string"&&question.notes?`<section><h3>Supported notes</h3><p>${escapeHtml(question.notes)}</p></section>`:"";
    $("browse-record-body").innerHTML=`${choiceSection}<section><h3>Correct answer</h3><p>${escapeHtml((question.correct_answers||[]).join("; "))}</p></section><section><h3>Rationale</h3><p>${escapeHtml(question.rationale||"")}</p></section>${notes}`;
    $("browse-record-json").textContent=JSON.stringify(question,null,2);
    $("record-view").scrollIntoView({behavior:"smooth",block:"start"});
  }
  async function stepQuestion(delta){
    const absolute=(browseState.page-1)*browseState.pageSize+browseState.currentIndex;
    const target=absolute+delta;if(target<0||target>=browseState.response.total)return;
    const targetPage=Math.floor(target/browseState.pageSize)+1;
    if(targetPage!==browseState.page) await browseQuestions(targetPage,false);
    const targetIndex=target%browseState.pageSize;
    const item=browseState.response.results[targetIndex];if(item)await loadQuestion(item,false,targetIndex);
  }
  function backToResults(){
    $("record-view").hidden=true;$("editor").hidden=true;$("preview").hidden=true;mode="repair";
    updateChapters();$("chapter").value=browseState.chapter;$("search").value=browseState.query;renderBrowseResults();
    requestAnimationFrame(()=>window.scrollTo({top:browseState.scrollY,behavior:"instant"}));
  }
  function openCurrentForRepair(){
    const question=browseState.currentQuestion;if(!question)return;
    mode="repair";$("type").value=question.type||question.question_type;$("record-view").hidden=true;openEditor(question,question);
  }
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
  function reopen(op){mode=op.operation_type;document.querySelectorAll("[data-mode]").forEach((button)=>button.classList.toggle("active",button.dataset.mode===mode));$("pack").value=op.pack_id;updateChapters();$("chapter").value=JSON.stringify({chapter:op.question.chapter,chapter_title:op.question.chapter_title});$("type").value=op.question.type;$("search-form").hidden=mode!=="repair";$("chapter-wrap").hidden=false;$("type-wrap").hidden=mode!=="addition";openEditor(op.question,op.original_question,op);}
  async function publishPending(op,button){button.disabled=true;button.textContent="Publishing…";try{const response=await json("/api/question-workbench/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({operation_id:op.operation_id})});showReadiness(response.readiness);await reload();}catch(error){button.disabled=false;button.textContent="Try publication again";alert(error.message);}}
  async function reload(){const response=await json("/api/question-workbench");data=response;showReadiness(data.readiness);renderPending();}
  async function init(){restoreBrowseState();data=await json("/api/question-workbench");fillSelectors();showReadiness(data.readiness);renderPending();setMode("repair");}
  document.querySelectorAll("[data-mode]").forEach((button)=>button.onclick=()=>setMode(button.dataset.mode));
  $("pack").onchange=()=>{browseState.packId=$("pack").value;browseState.chapter="";browseState.page=1;updateChapters();if(mode==="addition")openAddition();else void browseQuestions(1,false);refreshReadiness();};
  $("chapter").onchange=()=>{if(mode==="addition"&&!currentOperation){openAddition();renderMeta(collect());markChanges();}else if(mode==="repair"){browseState.chapter=$("chapter").value;browseState.page=1;void browseQuestions(1,false);}refreshReadiness();};
  $("type").onchange=()=>{order=[];renderItems(typeDef().kind==="text"?[]:items().length?items():[{label:"A",text:""},{label:"B",text:""}]);renderAnswers();renderMeta(collect());markChanges();refreshReadiness();};
  $("search-form").onsubmit=search;$("add-item").onclick=()=>{addItem();renderAnswers();};$("stem").oninput=$("rationale").oninput=$("notes").oninput=markChanges;
  $("preview-button").onclick=preview;$("back-to-edit").onclick=()=>{$("preview").hidden=true;$("editor").scrollIntoView({behavior:"smooth"});};$("final-action").onclick=finalAction;$("refresh").onclick=reload;
  $("back-to-results").onclick=backToResults;$("previous-question").onclick=()=>void stepQuestion(-1);$("next-question").onclick=()=>void stepQuestion(1);$("open-for-repair").onclick=openCurrentForRepair;
  document.addEventListener("keydown",(event)=>{if($("record-view").hidden||event.altKey||event.ctrlKey||event.metaKey)return;const target=event.target;if(target.matches("input,textarea,select,[contenteditable=true]"))return;if(event.key==="ArrowLeft"&&!$("previous-question").disabled){event.preventDefault();void stepQuestion(-1);}if(event.key==="ArrowRight"&&!$("next-question").disabled){event.preventDefault();void stepQuestion(1);}if(event.key==="Escape"){event.preventDefault();backToResults();}});
  init().catch((error)=>{document.body.innerHTML=`<main><section class="panel"><h1>Workbench unavailable</h1><p>${escapeHtml(error.message)}</p></section></main>`;});
})();
