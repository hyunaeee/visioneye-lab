'use strict';
const $ = (s) => document.querySelector(s);
const video = $('#video');
const reference = $('#source-video');
const demoEvents=[{track_id:1,direction:'IN',frame:102,timestamp:3.4},{track_id:2,direction:'IN',frame:153,timestamp:5.1},{track_id:3,direction:'IN',frame:203,timestamp:6.766666666667},{track_id:1,direction:'OUT',frame:290,timestamp:9.666666666667}];
let current={events:demoEvents,initial:0,totalIn:3,totalOut:1,duration:12,frames:360,origin:0,demo:true,name:'합성 보행 시나리오'};
function formatTime(t){t=Math.max(0,Number(t)||0);return String(Math.floor(t/60)).padStart(2,'0')+':'+(t%60).toFixed(2).padStart(5,'0');}
function goPanel(id){$('h1').textContent=({viewer:'분석 뷰어',models:'모델 비교',design:'실험 설계',results:'검증 결과'})[id]||'분석 뷰어';for(const p of document.querySelectorAll('.tab-panel'))p.hidden=p.id!==id;for(const b of document.querySelectorAll('.tab')){b.classList.toggle('active',b.dataset.panel===id);if(b.dataset.panel===id)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-panel]').forEach(b=>b.addEventListener('click',()=>goPanel(b.dataset.panel)));
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>goPanel(b.dataset.go)));
function eventList(){const box=$('#events');box.replaceChildren();current.events.forEach((e,i)=>{const b=document.createElement('button');b.type='button';b.className='event-row future';b.dataset.index=i;const icon=document.createElement('span');icon.className='event-icon'+(e.direction==='OUT'?' out':'');icon.textContent=e.direction==='IN'?'↘':'↗';const body=document.createElement('span');const strong=document.createElement('strong');strong.textContent=e.direction==='IN'?'입장 감지':'퇴장 감지';const small=document.createElement('small');small.textContent='TRACK '+String(e.track_id).padStart(2,'0')+' · '+e.direction;body.append(strong,small);const time=document.createElement('span');time.className='event-time';time.textContent=formatTime(e.timestamp-current.origin);b.append(icon,body,time);b.addEventListener('click',()=>requestSeek(e.timestamp-current.origin));box.append(b);});if(!current.events.length){const p=document.createElement('p');p.className='empty-state';p.textContent='출입 기록 없음';box.append(p);}$('#event-count').textContent=current.events.length+' EVENTS';}
function drawChart(){
  const w=1100,h=140,l=48,r=18,top=15,bottom=28,d=current.duration;
  const net=current.occupancyKnown===false,start=net?0:current.initial;
  let occ=start,peak=occ,low=0;
  for(const e of current.events){occ+=e.direction==='IN'?1:-1;peak=Math.max(peak,occ);if(net)low=Math.min(low,occ);}
  const step=Math.max(1,Math.ceil((peak-low)/4)),min=Math.floor(low/step)*step,max=min+step*4;
  const x=t=>l+Math.max(0,Math.min(d,t))/d*(w-l-r);
  const y=v=>h-bottom-((net?v:Math.max(0,v))-min)/(max-min)*(h-top-bottom);
  occ=start;let path=`M${x(0)},${y(occ)}`,markers='',grid='';
  for(const e of current.events){const t=e.timestamp-current.origin;path+=` H${x(t)} V${y(occ+=e.direction==='IN'?1:-1)}`;markers+=`<circle cx="${x(t)}" cy="${y(occ)}" r="4" fill="${e.direction==='IN'?'#c4f46b':'#8edbdf'}"/>`;}
  path+=` H${x(d)}`;
  for(let i=0;i<=4;i++){const v=min+i*step;grid+=`<line x1="${l}" y1="${y(v)}" x2="${w-r}" y2="${y(v)}" stroke="#2a343b"/><text x="5" y="${y(v)+4}" fill="#93a0a7" font-size="11">${v}</text>`;}
  for(let i=0;i<=4;i++)grid+=`<text x="${x(d*i/4)}" y="${h-4}" text-anchor="middle" fill="#93a0a7" font-size="11">${(d*i/4).toFixed(1)}s</text>`;
  $('#chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${net?'시간별 출입 순증감':'시간별 추정 재실 인원'}">${grid}<path d="${path} L${x(d)},${y(0)} L${x(0)},${y(0)} Z" fill="#c4f46b0c"/><path d="${path}" fill="none" stroke="#c4f46b" stroke-width="2"/>${markers}<line id="playhead" x1="${l}" x2="${l}" y1="5" y2="${h-bottom}" stroke="#f2f4ef" stroke-dasharray="4 4"/></svg>`;
}
function hasReference(){return Boolean(current.referenceURL);}
function syncReference(force=false){
  if(!hasReference()||reference.readyState<1)return;
  const target=Math.min(video.currentTime,reference.duration||current.duration);
  if(force||Math.abs(reference.currentTime-target)>.08)reference.currentTime=target;
  if(reference.playbackRate!==video.playbackRate)reference.playbackRate=video.playbackRate;
}
function pauseBoth(){video.pause();reference.pause();}
async function playBoth(){
  if(video.ended||video.currentTime>=current.duration-.025)await seek(0);
  syncReference(true);
  try{await Promise.all([video.play(),...(hasReference()?[reference.play()]:[])]);}
  catch{pauseBoth();toast('영상 재생 오류');}
}
function settleSeek(media,time){
  return new Promise((resolve,reject)=>{
    if(media.readyState<1){reject(new Error('영상 로딩 중'));return;}
    if(Math.abs(media.currentTime-time)<.002&&!media.seeking){resolve();return;}
    let timer;
    const cleanup=()=>{clearTimeout(timer);media.removeEventListener('seeked',done);media.removeEventListener('error',failed);};
    const done=()=>{cleanup();if(Math.abs(media.currentTime-time)>.06)reject(new Error('영상 탐색 미지원'));else resolve();};
    const failed=()=>{cleanup();reject(new Error('영상 시점 이동 오류'));};
    media.addEventListener('seeked',done,{once:true});media.addEventListener('error',failed,{once:true});
    timer=setTimeout(failed,5000);media.currentTime=time;
  });
}
async function seek(time){
  const target=Math.min(Math.max(0,time),Math.max(0,current.duration-.001));
  await Promise.all([settleSeek(video,target),...(hasReference()?[settleSeek(reference,target)]:[])]);
  update();
}
function requestSeek(time){seek(time).catch(e=>toast(e.message));}
function update(){
  const t=video.currentTime||0,c=VisionData.counts(current,t);
  $('#in-value').textContent=c.in;$('#out-value').textContent=c.out;
  $('#occupancy-value').textContent=current.occupancyKnown===false?c.in-c.out:c.occupancy;
  $('#occupancy-value').classList.toggle('negative',c.rawOccupancy<0);
  $('#occupancy-note').textContent=current.occupancyKnown===false?'IN − OUT · 초기 인원 미확정':c.rawOccupancy<0?'원시 재실 '+c.rawOccupancy+'명 · 초기값/누락 확인':'초기 인원 '+current.initial+' + IN − OUT';
  $('#clock').textContent=formatTime(t)+' / '+formatTime(current.duration);
  $('#play').textContent=video.paused?'재생':'일시정지';
  $('#timeline').value=t;$('#timeline').max=current.duration;
  $('#sync-state').textContent=hasReference()?'동기화':'분석 영상';
  document.querySelectorAll('.event-row').forEach((b,i)=>{b.classList.toggle('future',current.events[i].timestamp>t+current.origin+.001);b.classList.toggle('current',Math.abs(current.events[i].timestamp-t-current.origin)<.25);});
  const line=$('#playhead');if(line){const x=48+Math.min(1,t/current.duration)*(1100-48-18);line.setAttribute('x1',x);line.setAttribute('x2',x);}
}
$('#play').addEventListener('click',()=>video.paused?playBoth():pauseBoth());
$('#back').addEventListener('click',()=>requestSeek(video.currentTime-5));
$('#forward').addEventListener('click',()=>requestSeek(video.currentTime+5));
$('#timeline').addEventListener('input',()=>{pauseBoth();requestSeek(Number($('#timeline').value));});
$('#speed').addEventListener('change',()=>{video.playbackRate=Number($('#speed').value);reference.playbackRate=video.playbackRate;});
video.addEventListener('timeupdate',()=>{syncReference();update();});
video.addEventListener('seeking',()=>syncReference());
video.addEventListener('pause',()=>reference.pause());
video.addEventListener('ended',pauseBoth);
['seeked','play','pause','loadedmetadata','ended'].forEach(e=>video.addEventListener(e,update));
video.addEventListener('error',()=>{$('#video-error').hidden=false;pauseBoth();});
reference.addEventListener('error',()=>{if(hasReference()){$('#source-error').hidden=false;pauseBoth();}});
function checkAlignment(){
  if(!hasReference()||video.readyState<1||reference.readyState<1)return;
  if(Math.abs(video.duration-reference.duration)>.13){pauseBoth();$('#source-error').hidden=false;$('#source-error').textContent='원본·분석 길이 불일치';}
}
video.addEventListener('loadedmetadata',checkAlignment);reference.addEventListener('loadedmetadata',checkAlignment);
document.querySelectorAll('[data-fullscreen]').forEach(b=>b.addEventListener('click',()=>{
  const target=document.getElementById(b.dataset.fullscreen);
  target.requestFullscreen?.().catch(()=>toast('전체화면 미지원'));
}));
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4500);}
$('#open-import').addEventListener('click',()=>$('#import-dialog').showModal());
$('#close-import').addEventListener('click',()=>$('#import-dialog').close());
$('.brand').addEventListener('click',e=>{e.preventDefault();goPanel('viewer');});
let objectURLs=[],loadGeneration=0;
const choices={
  crowd:{video:'crowd-analysis.mp4',source:'crowd-source.mp4',poster:'crowd-analysis-poster.jpg',sourcePoster:'crowd-source-poster.jpg',csv:'crowd-events.csv',json:'crowd-summary.json',name:'다인 보행',overlay:true,width:1280,height:720},
  higgsfield:{video:'higgsfield-overlay.mp4',source:'higgsfield-source.mp4',poster:'higgsfield-overlay-poster.jpg',sourcePoster:'higgsfield-source-poster.jpg',csv:'higgsfield-events.csv',json:'higgsfield-summary.json',name:'2인 보행',overlay:true,width:1280,height:720},
  demo:{video:'demo.mp4',poster:'poster.jpg',csv:'events.csv',json:'summary.json',name:'합성 집계',width:960,height:540}
};
function refreshSession(){
  $('.session-index').textContent=current.benchmark?'BENCH':current.key==='crowd'?'EXP–002':current.key==='higgsfield'?'EXP–001':current.demo?'DEMO':'LOCAL';
  video.setAttribute('aria-label',current.name+' 분석 영상');reference.setAttribute('aria-label',current.name+' 원본 영상');
  $('#session-name').textContent=current.name;
  $('#mode-badge').textContent=current.benchmark?(current.benchmarkGroup==='cached_tracker'?'YOLO CACHE':'PIPELINE'):current.generated?'AI VIDEO / YOLO':current.demo?'SYNTHETIC':'LOCAL FILE';
  $('#in-total').textContent='전체 기록 '+current.totalIn+'명';$('#out-total').textContent='전체 기록 '+current.totalOut+'명';
  const net=current.occupancyKnown===false;
  $('#occupancy-label').textContent=net?'현재 출입 순증감':'현재 추정 재실';$('#occupancy-tag').textContent=net?'NET CHANGE':'ESTIMATE';
  $('#final-label').textContent=net?'전체 출입 순증감':'최종 재실';$('#chart-title').textContent=net?'출입 순증감':'재실 인원';
  $('#final-value').textContent=net?current.totalIn-current.totalOut:Math.max(0,current.initial+current.totalIn-current.totalOut);
  $('#run-meta').textContent=current.frames.toLocaleString()+'프레임 · '+current.duration.toFixed(1)+'초';
  $('#source-meta').textContent=current.width?current.width+' × '+current.height+' · '+current.fps+' FPS':'INPUT';
  $('#video-meta').textContent=current.analysisLabel||(current.overlay?'YOLO26 · BYTETRACK':current.demo?'SYNTHETIC':'ANALYSIS');
  $('#overlay-label').textContent=current.overlayLabel||(current.overlay?'채움 12% · 시각화용':'분석 파일');
  $('#viewer-notice').textContent=current.benchmark?'AI 생성 원본 · '+current.analysisLabel+' · 저장된 결과 재생 · 시각화용 · 익명화 없음'+(current.benchmarkGroup==='cached_tracker'?' · 동일 YOLO 검출 캐시 · 추적 시간은 모델 비교에서 확인':' · 렌더·영상 저장은 새 파이프라인 FPS 측정 제외'):current.overlay?'Higgsfield 생성 영상 · 실제 YOLO26 추론 · 반투명 시각화 · 익명화 없음':current.demo?'합성 좌표 · 집계 검증 · YOLO 추론 제외':'사용자 파일 · 추가 검출·마스킹 없음';
  $('#chart-caption').textContent=net?'순증감 = IN − OUT · 초기 실내 인원 미확정':'재실 = 초기 인원 + IN − OUT · 기록 시작 '+current.origin.toFixed(3)+'초';
  $('#source-link').hidden=!current.referenceURL;$('#source-link').href=current.referenceURL||'#';
  $('#run-data-link').hidden=!current.builtin;if(current.summaryURL)$('#run-data-link').href=current.summaryURL;
  $('#no-source').hidden=hasReference();
  eventList();drawChart();update();
}
function installMedia(next,resultURL,referenceURL,poster,sourcePoster){
  pauseBoth();current=next;current.referenceURL=referenceURL||null;
  $('#video-error').hidden=true;$('#source-error').hidden=true;$('#source-error').textContent='원본 재생 오류';
  video.removeAttribute('poster');reference.removeAttribute('poster');
  if(poster)video.poster=poster;if(sourcePoster)reference.poster=sourcePoster;
  video.src=resultURL;video.load();
  if(referenceURL)reference.src=referenceURL;else reference.removeAttribute('src');reference.load();
  $('#speed').value='1';video.playbackRate=1;reference.playbackRate=1;
  refreshSession();
}
async function loadBuiltin(key){
  const choice=choices[key];if(!choice)return;
  const revision=++loadGeneration;$('#run-select').disabled=true;pauseBoth();
  try{
    const fetchText=async name=>{const response=await fetch('assets/'+name);if(!response.ok)throw new Error('실험 데이터 로딩 오류');return response.text();};
    const [csv,json]=await Promise.all([fetchText(choice.csv),fetchText(choice.json)]);
    const next=VisionData.parse(csv,json);if(revision!==loadGeneration)return false;
    Object.assign(next,{...choice,key,demo:key==='demo',generated:key!=='demo',builtin:true,summaryURL:'assets/'+choice.json});
    const old=objectURLs;objectURLs=[];
    installMedia(next,'assets/'+choice.video,choice.source?'assets/'+choice.source:null,choice.poster?'assets/'+choice.poster:null,choice.sourcePoster?'assets/'+choice.sourcePoster:null);
    old.forEach(url=>URL.revokeObjectURL(url));$('#run-select').value=key;return true;
  }catch(error){if(revision===loadGeneration){toast(error.message||'실험 데이터 로딩 오류');$('#run-select').value=current.key||'local';}return false;}
  finally{if(revision===loadGeneration)$('#run-select').disabled=false;}
}
$('#run-select').addEventListener('change',()=>loadBuiltin($('#run-select').value));
$('#reset-demo').addEventListener('click',()=>loadBuiltin('demo'));
$('#open-synthetic').addEventListener('click',async()=>{await loadBuiltin('demo');goPanel('viewer');});
$('#open-generated').addEventListener('click',async()=>{await loadBuiltin('higgsfield');goPanel('viewer');});
$('#open-crowd')?.addEventListener('click',async()=>{await loadBuiltin('crowd');goPanel('viewer');});
function inspectVideo(url){return new Promise((resolve,reject)=>{
  const probe=document.createElement('video');probe.preload='metadata';
  const timer=setTimeout(()=>finish(new Error('영상 정보 로딩 오류')),12000);
  function finish(error){clearTimeout(timer);probe.onloadedmetadata=null;probe.onerror=null;const duration=probe.duration;probe.removeAttribute('src');probe.load();if(error)reject(error);else resolve(duration);}
  probe.onloadedmetadata=()=>finish(Number.isFinite(probe.duration)&&probe.duration>0?null:new Error('영상 길이 오류'));
  probe.onerror=()=>finish(new Error('영상 형식 오류 · H.264 MP4 권장'));probe.src=url;
});}
$('#import-form').addEventListener('submit',async event=>{
  event.preventDefault();const submit=event.currentTarget.querySelector('[type="submit"]');if(submit.disabled)return;
  const vf=$('#video-file').files[0],cf=$('#events-file').files[0],sf=$('#summary-file').files[0],rf=$('#source-file').files[0];
  if(!vf||!cf||!sf)return;
  let pendingURLs=[];$('#import-error').textContent='';submit.disabled=true;submit.textContent='파일 확인';
  try{
    if(cf.size>5*1024*1024||sf.size>1024*1024)throw new Error('CSV 최대 5MB · JSON 최대 1MB');
    const [csv,json]=await Promise.all([cf.text(),sf.text()]);const next=VisionData.parse(csv,json);
    const resultURL=URL.createObjectURL(vf);pendingURLs.push(resultURL);next.duration=await inspectVideo(resultURL);
    let referenceURL=null;
    if(rf){referenceURL=URL.createObjectURL(rf);pendingURLs.push(referenceURL);const sourceDuration=await inspectVideo(referenceURL);if(Math.abs(sourceDuration-next.duration)>.13)throw new Error('원본·분석 길이 불일치');}
    if(next.events.some(e=>e.timestamp-next.origin>next.duration+.1))throw new Error('이벤트 시각·영상 길이 불일치');
    next.name=vf.name;next.key='local';const old=objectURLs;loadGeneration++;
    objectURLs=pendingURLs;pendingURLs=[];installMedia(next,resultURL,referenceURL);
    old.forEach(url=>URL.revokeObjectURL(url));$('#run-select').disabled=false;$('#run-select').value='local';goPanel('viewer');$('#import-dialog').close();toast('파일 로딩 완료');
  }catch(error){$('#import-error').textContent=error.message||'파일 로딩 오류';}
  finally{pendingURLs.forEach(url=>URL.revokeObjectURL(url));submit.disabled=false;submit.textContent='뷰어에서 열기';}
});
function viewerCounts(){const c=VisionData.counts(current,video.currentTime);return {...c,occupancy:current.occupancyKnown===false?null:c.occupancy,netChange:c.in-c.out,displayMetric:current.occupancyKnown===false?'netChange':'occupancy',displayValue:current.occupancyKnown===false?c.in-c.out:c.occupancy};}
function playbackState(){return {time:video.currentTime,referenceTime:hasReference()?reference.currentTime:null,comparison:hasReference(),paused:video.paused,driftMs:hasReference()?Math.round(Math.abs(video.currentTime-reference.currentTime)*1000):null};}
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  const register=tool=>{try{Promise.resolve(document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch{}};
  register({name:'read_visioneye_session',title:'분석 기록 읽기',description:'현재 기록의 출입 집계와 원본·분석 영상의 재생 시각을 읽습니다.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute(input){if(!input||typeof input!=='object'||Object.keys(input).length)throw new Error('입력은 빈 객체여야 합니다.');return {name:current.name,syntheticDemo:current.demo,aiGeneratedVideo:!!current.generated,duration:current.duration,events:current.events.length,totalIn:current.totalIn,totalOut:current.totalOut,...playbackState(),...viewerCounts()};}});
  register({name:'seek_visioneye_video',title:'비교 영상 시점 이동',description:'원본·분석 영상을 함께 일시정지하고 지정한 초로 이동합니다.',inputSchema:{type:'object',properties:{seconds:{type:'number',minimum:0}},required:['seconds'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},async execute(input){if(!input||typeof input.seconds!=='number'||!Number.isFinite(input.seconds)||input.seconds<0||input.seconds>current.duration||Object.keys(input).some(k=>k!=='seconds'))throw new Error('seconds는 현재 영상 길이 안의 유한한 숫자여야 합니다.');if(video.readyState<1||(hasReference()&&reference.readyState<1))throw new Error('영상 로딩 중');pauseBoth();goPanel('viewer');await seek(input.seconds);return {...playbackState(),...viewerCounts()};}});
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
// Comparison schema v1: one row per model/clip. Missing measurements stay empty.
const modelComparison={runs:[],blocked:[],revision:0};
const comparisonStatus={completed:'완료',pending:'준비',failed:'실패',blocked:'보류'};
function comparisonNumber(value,digits=0){return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';}
function comparisonText(tag,text,className){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;}
function comparisonLink(url,label){
  if(typeof url!=='string'||!url.trim())return null;
  try{const target=new URL(url,document.baseURI);if(!['http:','https:'].includes(target.protocol))return null;const a=comparisonText('a',label,'comparison-link');a.href=target.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}
}
function comparisonMetric(value,range,digits=2){
  const cell=document.createElement('td');cell.className='comparison-numeric';cell.append(comparisonText('strong',comparisonNumber(value,digits)));
  if(typeof value==='number'&&Array.isArray(range)&&range.length===2&&range.every(v=>typeof v==='number'&&Number.isFinite(v)))cell.append(comparisonText('small',range.map(v=>comparisonNumber(v,digits)).join('–'),'comparison-range'));
  return cell;
}
function comparisonReview(row,key){
  const cell=document.createElement('td');cell.className='comparison-review-cell';
  const result=row.status==='completed'?row.review?.[key]:null;
  const matched=result?.matched,annotations=row.review?.annotations;
  cell.append(comparisonText('strong',typeof matched==='number'&&typeof annotations==='number'?comparisonNumber(matched)+' / '+comparisonNumber(annotations):'—'));
  if(result)cell.append(comparisonText('small','미대응 예측 '+comparisonNumber(result.fp)+' · 검수 '+comparisonNumber(result.fn)));
  return cell;
}
function comparisonInput(value){return Array.isArray(value)?value.map(v=>comparisonNumber(v)).join('×'):comparisonNumber(value);}
function comparisonRecords(row){
  const cell=document.createElement('td');cell.className='comparison-records';
  const key='benchmark-'+row.id;
  if(row.status==='completed'&&row.assets_ready===true&&choices[key]){
    const open=comparisonText('button','보기','button comparison-open');open.type='button';
    open.addEventListener('click',async()=>{open.disabled=true;open.textContent='로딩';try{if(await loadBuiltin(key))goPanel('viewer');}finally{open.disabled=false;open.textContent='보기';}});cell.append(open);
  }else cell.append(comparisonText('span',row.status==='completed'?(row.asset_prefix?'영상 준비':'영상 없음'):comparisonStatus[row.status]||'미측정','comparison-muted'));
  const samples=Array.isArray(row.samples)?row.samples:[];
  const repeats=typeof row.repeats==='number'?row.repeats:samples.length;
  if(repeats>0||samples.length||row.raw_url||row.notes?.length||row.reason){
    const details=document.createElement('details');details.append(comparisonText('summary',repeats>0?comparisonNumber(repeats)+'회':'기록'));
    for(const [index,sample] of samples.entries()){
      const value=row.group==='pipeline'?'FPS '+comparisonNumber(sample.pipeline_fps,2):'p50 '+comparisonNumber(sample.tracker_p50_ms,2)+' / p95 '+comparisonNumber(sample.tracker_p95_ms,2)+' ms';
      const line=comparisonText('p',comparisonNumber(sample.repeat??index+1)+'회 · '+value,'comparison-sample');
      if(typeof sample.total_in==='number'&&typeof sample.total_out==='number')line.append(comparisonText('small','IN '+comparisonNumber(sample.total_in)+' / OUT '+comparisonNumber(sample.total_out)));
      if(typeof sample.unique_track_ids==='number')line.append(comparisonText('small','ID '+comparisonNumber(sample.unique_track_ids)));
      const raw=comparisonLink(sample.raw_url,'원자료 ↗');if(raw)line.append(raw);details.append(line);
    }
    if(!samples.length&&repeats>0)details.append(comparisonText('p','개별 실행 수치는 원자료에서 확인합니다.','comparison-muted'));
    if(row.reason)details.append(comparisonText('p',String(row.reason),'comparison-muted'));
    for(const note of Array.isArray(row.notes)?row.notes:[])details.append(comparisonText('p',String(note),'comparison-muted'));
    const raw=comparisonLink(row.raw_url,'원자료 ↗');if(raw)details.append(raw);
    cell.append(details);
  }
  return cell;
}
function renderComparisonTable(group,target){
  const tbody=$(target);tbody.replaceChildren();const clip=$('#comparison-clip').value;
  const rows=modelComparison.runs.filter(row=>row.group===group&&row.status!=='blocked'&&(clip==='all'||row.clip===clip));
  for(const row of rows){
    const tr=document.createElement('tr'),ready=row.status==='completed';
    const name=document.createElement('th');name.scope='row';name.append(comparisonText('strong',String(row.model)));
    name.append(comparisonText('small',comparisonStatus[row.status]||'미측정','comparison-row-status '+(ready?'is-complete':'')));tr.append(name);
    tr.append(comparisonText('td',row.clip==='crowd'?'다인':'2인'));
    const config=document.createElement('td');
    if(group==='pipeline')config.textContent=(row.precision||'—')+' · '+comparisonInput(row.input_size);
    else if(row.reid){config.append(comparisonText('span','ON · '+comparisonInput(row.reid.input_size)));config.append(comparisonText('small',String(row.reid.device||'—')));if(row.reid.model)config.title=String(row.reid.model);}
    else config.textContent='OFF';tr.append(config);
    tr.append(comparisonText('td',ready?comparisonNumber(row.total_in)+' / '+comparisonNumber(row.total_out):'—','comparison-numeric'));
    if(group==='pipeline')tr.append(comparisonMetric(ready?row.pipeline_fps:null,row.pipeline_fps_range));
    else {tr.append(comparisonMetric(ready?row.tracker_p50_ms:null,row.tracker_p50_ms_range));tr.append(comparisonMetric(ready?row.tracker_p95_ms:null,row.tracker_p95_ms_range));}
    tr.append(comparisonReview(row,'strict'),comparisonReview(row,'expanded_0_5s'));
    tr.append(comparisonText('td',ready?comparisonNumber(row.unique_track_ids):'—','comparison-numeric'));
    if(group==='pipeline')tr.append(comparisonText('td',ready&&typeof row.peak_vram_mib==='number'?comparisonNumber(row.peak_vram_mib,1)+' MiB':'—','comparison-numeric'));
    tr.append(comparisonRecords(row));tbody.append(tr);
  }
  if(!rows.length){const tr=document.createElement('tr'),cell=comparisonText('td',modelComparison.runs.length?'이 영상의 기록 없음':'측정 기록 준비 중','comparison-empty');cell.colSpan=10;tr.append(cell);tbody.append(tr);}
}
function registerComparisonRuns(){
  let group=$('#benchmark-options');
  for(const row of modelComparison.runs){
    if(row.status!=='completed'||row.assets_ready!==true||!/^bench-[a-z0-9-]+$/.test(row.asset_prefix||'')||!['pipeline','cached_tracker'].includes(row.group))continue;
    const prefix=row.asset_prefix,key='benchmark-'+row.id,clip=row.clip==='crowd'?'다인':'2인';
    const source=row.clip==='crowd'?'crowd':'higgsfield';
    choices[key]={video:prefix+'.mp4',poster:prefix+'-poster.jpg',source:source+'-source.mp4',sourcePoster:source+'-source-poster.jpg',csv:prefix+'-events.csv',json:prefix+'-summary.json',name:clip+' · '+row.model,overlay:true,width:1280,height:720,benchmark:true,benchmarkGroup:row.group,occupancyKnown:false,analysisLabel:row.group==='cached_tracker'?'YOLO 캐시 · '+row.model:row.model+' · ByteTrack',overlayLabel:row.overlay_label||'반투명 · 시각화용'};
    if(!group){group=document.createElement('optgroup');group.id='benchmark-options';group.label='모델 비교';$('#run-select').append(group);}
    let option=[...group.children].find(option=>option.value===key);
    if(!option){option=document.createElement('option');option.value=key;group.append(option);}option.textContent=clip+' · '+row.model;
  }
}
function renderComparison(){
  registerComparisonRuns();renderComparisonTable('pipeline','#pipeline-results');renderComparisonTable('cached_tracker','#tracker-results');
  const box=$('#comparison-blocked');box.replaceChildren();box.hidden=!modelComparison.blocked.length;
  for(const item of modelComparison.blocked){const p=document.createElement('p');p.append(comparisonText('strong',String(item.model||'모델')+' · 보류'));p.append(comparisonText('span',String(item.reason||'실행되지 않았습니다.')));box.append(p);}
}
async function loadComparison(){
  const revision=++modelComparison.revision;$('#comparison-reload').disabled=true;$('#comparison-load-state').textContent='비교 기록을 불러오는 중입니다.';
  try{
    const response=await fetch('assets/comparison-results.json',{cache:'no-store'});
    if(!response.ok)throw new Error(response.status===404?'준비':'오류');
    const data=await response.json();if(revision!==modelComparison.revision)return;
    if(data?.schema_version!==1||!Array.isArray(data.runs))throw new Error('형식');
    const ids=new Set();
    for(const row of data.runs){
      if(!row||typeof row.id!=='string'||!/^[a-z0-9_-]+$/i.test(row.id)||ids.has(row.id)||typeof row.model!=='string'||!comparisonStatus[row.status]||(row.status!=='blocked'&&(!['pipeline','cached_tracker'].includes(row.group)||!['crowd','two-person'].includes(row.clip))))throw new Error('형식');
      ids.add(row.id);
    }
    modelComparison.runs=data.runs;
    modelComparison.blocked=[...(Array.isArray(data.blocked)?data.blocked:[]),...data.runs.filter(row=>row.status==='blocked')];
    const total=data.runs.filter(row=>row.status!=='blocked').length,done=data.runs.filter(row=>row.status==='completed').length;
    $('#comparison-status').textContent=total?done+' / '+total+' 완료':'준비';
    $('#comparison-load-state').textContent=done?'반복 중앙값 · 범위 · 미측정은 —':'완료된 측정 기록이 없습니다.';
    const context=[data.updated_at,data.environment?.gpu,data.environment?.python?'Python '+data.environment.python:null].filter(value=>typeof value==='string'&&value.trim());
    $('#comparison-environment').textContent=context.length?context.join(' · '):'같은 원본 · 서로 다른 측정 범위';
    $('#comparison-json-link').hidden=false;
    const raw=comparisonLink(data.raw_url,'원자료 ↗');$('#comparison-raw-link').hidden=!raw;if(raw){$('#comparison-raw-link').href=raw.href;$('#comparison-raw-link').target='_blank';$('#comparison-raw-link').rel='noopener noreferrer';}
    renderComparison();
  }catch(error){
    if(revision!==modelComparison.revision)return;
    const previous=modelComparison.runs.length>0;
    $('#comparison-status').textContent=previous?'이전 기록':'준비';
    $('#comparison-load-state').textContent=previous?'새 기록을 불러오지 못했습니다. 현재 표는 이전 기록입니다.':error.message==='준비'?'비교 기록 준비 중 · 기존 영상은 계속 확인할 수 있습니다.':'비교 기록을 읽지 못했습니다. 새로고침으로 다시 확인하세요.';
  }finally{if(revision===modelComparison.revision)$('#comparison-reload').disabled=false;}
}
$('#comparison-clip').addEventListener('change',renderComparison);
$('#comparison-reload').addEventListener('click',loadComparison);
loadBuiltin('crowd');
loadComparison();
