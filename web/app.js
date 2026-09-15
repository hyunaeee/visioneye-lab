'use strict';
const $ = (s) => document.querySelector(s);
const video = $('#video');
const reference = $('#source-video');
const demoEvents=[{track_id:1,direction:'IN',frame:102,timestamp:3.4},{track_id:2,direction:'IN',frame:153,timestamp:5.1},{track_id:3,direction:'IN',frame:203,timestamp:6.766666666667},{track_id:1,direction:'OUT',frame:290,timestamp:9.666666666667}];
let current={events:demoEvents,initial:0,totalIn:3,totalOut:1,duration:12,frames:360,origin:0,demo:true,name:'합성 보행 시나리오'};
function formatTime(t){t=Math.max(0,Number(t)||0);return String(Math.floor(t/60)).padStart(2,'0')+':'+(t%60).toFixed(2).padStart(5,'0');}
function goPanel(id){$('h1').textContent=({viewer:'분석 뷰어',design:'실험 설계',results:'검증 결과'})[id]||'분석 뷰어';for(const p of document.querySelectorAll('.tab-panel'))p.hidden=p.id!==id;for(const b of document.querySelectorAll('.tab')){b.classList.toggle('active',b.dataset.panel===id);if(b.dataset.panel===id)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}window.scrollTo({top:0,behavior:'instant'});}
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
  $('.session-index').textContent=current.key==='crowd'?'EXP–002':current.key==='higgsfield'?'EXP–001':current.demo?'DEMO':'LOCAL';
  video.setAttribute('aria-label',current.name+' 분석 영상');reference.setAttribute('aria-label',current.name+' 원본 영상');
  $('#session-name').textContent=current.name;
  $('#mode-badge').textContent=current.generated?'AI VIDEO / YOLO':current.demo?'SYNTHETIC':'LOCAL FILE';
  $('#in-total').textContent='전체 기록 '+current.totalIn+'명';$('#out-total').textContent='전체 기록 '+current.totalOut+'명';
  const net=current.occupancyKnown===false;
  $('#occupancy-label').textContent=net?'현재 출입 순증감':'현재 추정 재실';$('#occupancy-tag').textContent=net?'NET CHANGE':'ESTIMATE';
  $('#final-label').textContent=net?'전체 출입 순증감':'최종 재실';$('#chart-title').textContent=net?'출입 순증감':'재실 인원';
  $('#final-value').textContent=net?current.totalIn-current.totalOut:Math.max(0,current.initial+current.totalIn-current.totalOut);
  $('#run-meta').textContent=current.frames.toLocaleString()+'프레임 · '+current.duration.toFixed(1)+'초';
  $('#source-meta').textContent=current.width?current.width+' × '+current.height+' · '+current.fps+' FPS':'INPUT';
  $('#video-meta').textContent=current.overlay?'YOLO26 · BYTETRACK':current.demo?'SYNTHETIC':'ANALYSIS';
  $('#overlay-label').textContent=current.overlay?'채움 12% · 시각화용':'분석 파일';
  $('#viewer-notice').textContent=current.overlay?'Higgsfield 생성 영상 · 실제 YOLO26 추론 · 반투명 시각화 · 익명화 없음':current.demo?'합성 좌표 · 집계 검증 · YOLO 추론 제외':'사용자 파일 · 추가 검출·마스킹 없음';
  $('#chart-caption').textContent=net?'순증감 = IN − OUT · 초기 실내 인원 미확정':'재실 = 초기 인원 + IN − OUT · 기록 시작 '+current.origin.toFixed(3)+'초';
  $('#source-link').hidden=!current.referenceURL;$('#source-link').href=current.referenceURL||'#';
  $('#run-data-link').hidden=!current.builtin;if(current.summaryURL)$('#run-data-link').href=current.summaryURL;
  $('#no-source').hidden=hasReference();
  eventList();drawChart();update();
}
function installMedia(next,resultURL,referenceURL,poster,sourcePoster){
  pauseBoth();current=next;current.referenceURL=referenceURL||null;
  $('#video-error').hidden=true;$('#source-error').hidden=true;
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
    const next=VisionData.parse(csv,json);if(revision!==loadGeneration)return;
    Object.assign(next,{...choice,key,demo:key==='demo',generated:key!=='demo',builtin:true,summaryURL:'assets/'+choice.json});
    const old=objectURLs;objectURLs=[];
    installMedia(next,'assets/'+choice.video,choice.source?'assets/'+choice.source:null,'assets/'+choice.poster,choice.sourcePoster?'assets/'+choice.sourcePoster:null);
    old.forEach(url=>URL.revokeObjectURL(url));$('#run-select').value=key;
  }catch(error){if(revision===loadGeneration){toast(error.message||'실험 데이터 로딩 오류');$('#run-select').value=current.key||'local';}}
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
loadBuiltin('crowd');
