'use strict';
// Parsing is separate from playback so an invalid import never replaces a run.
globalThis.VisionData = (() => {
  function integer(value, name) {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(name + ' 값은 0 이상의 정수여야 합니다.');
    return value;
  }
  function parse(csv, summaryText) {
    let s;
    try { s=JSON.parse(summaryText); } catch { throw new Error('summary.json을 읽을 수 없습니다. JSON 형식을 확인하세요.'); }
    if (!s || typeof s!=='object' || Array.isArray(s)) throw new Error('유효한 실험 요약이 아닙니다.');
    const initial=integer(s.config?.initial_occupancy ?? 0,'초기 인원');
    const totalIn=integer(s.total_in,'total_in');
    const totalOut=integer(s.total_out,'total_out');
    const frames=integer(s.processed_frames,'processed_frames');
    if (!frames) throw new Error('처리한 프레임이 없는 실행입니다.');
    const fps=Number(s.source_fps);
    if (!Number.isFinite(fps) || fps<=0) throw new Error('source_fps 값이 올바르지 않습니다.');
    const origin=s.recording_start_seconds ?? 0;
    if (typeof origin!=='number' || !Number.isFinite(origin) || origin<0) throw new Error('기록 시작 시각이 올바르지 않습니다.');
    const lines=csv.replace(/^\uFEFF/,'').trim().split(/\r?\n/).filter(x=>x.trim());
    const fields=line=>line.split(',').map(v=>v.trim().replace(/^"(.*)"$/,'$1'));
    const head=fields(lines.shift() ?? '');
    const names=['track_id','direction','frame','timestamp'];
    if(head.length!==4 || names.some(n=>!head.includes(n))) throw new Error('CSV 헤더는 track_id,direction,frame,timestamp 네 열이어야 합니다.');
    if(lines.length>5000) throw new Error('한 번에 최대 5,000개 이벤트를 열 수 있습니다. 짧은 실행으로 나눠주세요.');
    const seen=new Set();
    const events=lines.map((line,i)=>{
      const cells=fields(line);
      if(cells.length!==4) throw new Error('CSV '+(i+2)+'행의 열 개수가 올바르지 않습니다.');
      const row=Object.fromEntries(head.map((h,j)=>[h,cells[j]]));
      if(!/^\d+$/.test(row.track_id)||!/^\d+$/.test(row.frame)||!/^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(row.timestamp)) throw new Error('CSV '+(i+2)+'행의 숫자 형식을 확인하세요.');
      const e={track_id:integer(Number(row.track_id),'track_id'),frame:integer(Number(row.frame),'frame'),direction:row.direction,timestamp:Number(row.timestamp)};
      if(!['IN','OUT'].includes(e.direction)||!Number.isFinite(e.timestamp)||e.timestamp<origin-0.001) throw new Error('CSV '+(i+2)+'행의 방향 또는 시각이 올바르지 않습니다.');
      const key=[e.track_id,e.frame,e.direction].join(':');
      if(seen.has(key)) throw new Error('동일한 출입 이벤트가 중복되어 있습니다.');
      seen.add(key);return e;
    }).sort((a,b)=>a.timestamp-b.timestamp||a.frame-b.frame);
    if(events.filter(e=>e.direction==='IN').length!==totalIn||events.filter(e=>e.direction==='OUT').length!==totalOut) throw new Error('CSV의 IN/OUT 수와 요약이 다릅니다. 같은 실행 폴더의 파일을 선택하세요.');
    if(s.occupancy!==Math.max(0,initial+totalIn-totalOut)||(s.raw_occupancy!==undefined&&s.raw_occupancy!==initial+totalIn-totalOut)) throw new Error('요약의 재실 인원과 출입 집계가 일치하지 않습니다.');
    return {events,initial,totalIn,totalOut,frames,origin,fps,duration:frames/fps,demo:false,occupancyKnown:s.occupancy_ground_truth_available!==false,sourceMode:String(s.mode??'unknown'),privacy:String(s.privacy??'unknown')};
  }
  function counts(run,time){
    const events=run.events.filter(e=>e.timestamp<=time+run.origin+.001);
    const ins=events.filter(e=>e.direction==='IN').length,outs=events.length-ins;
    return {in:ins,out:outs,rawOccupancy:run.initial+ins-outs,occupancy:Math.max(0,run.initial+ins-outs)};
  }
  return {parse,counts};
})();
