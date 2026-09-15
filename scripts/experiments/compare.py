"""Fixed-input detector pipelines and cached-box tracker ablations, CUDA serialized."""
from __future__ import annotations
import argparse,csv,hashlib,importlib,json,os,platform,re,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PUB=ROOT
from paths import RUNTIME,configure_cache
sys.path.insert(0,str(PUB/'visioneye'))
configure_cache()
import cv2,numpy as np,torch
from analytics import DirectionalCounter

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stats(a):
    return {'calls':len(a),'total_seconds':round(sum(a),6),'p50_ms':round(float(np.median(a))*1000,3),'p95_ms':round(float(np.percentile(a,95))*1000,3),'mean_ms':round(float(np.mean(a))*1000,3)} if a else None
def sync():
    if torch.cuda.is_available():torch.cuda.synchronize()
def safe_meta(x):
    if isinstance(x,dict):return {k:safe_meta(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [safe_meta(v) for v in x]
    if isinstance(x,Path):return x.name
    if isinstance(x,str) and (re.match(r'^[A-Za-z]:[\\/]',x) or x.startswith('/')):return Path(x).name
    return x

class GPUProbe:
    def __init__(self):self.samples=[];self.stop=threading.Event();self.thread=None
    def start(self):
        try:
            import pynvml
            pynvml.nvmlInit();self.nv=pynvml;self.handle=pynvml.nvmlDeviceGetHandleByIndex(0)
            def sample():
                while not self.stop.is_set():
                    try:self.samples.append(self.nv.nvmlDeviceGetMemoryInfo(self.handle).used/1048576)
                    except Exception:pass
                    self.stop.wait(.1)
            self.thread=threading.Thread(target=sample,daemon=True);self.thread.start()
        except Exception:pass
    def finish(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=1)
        return {'device_used_peak_mib':round(max(self.samples),1) if self.samples else None,'sample_count':len(self.samples),'scope':'Whole GPU used memory sampled every 100 ms, includes display and other processes; not model-only VRAM.'}

def references(clip):
    if clip=='crowd':return json.loads((PUB/'web/assets/crowd-source-review.json').read_text(encoding='utf-8'))['manual_events']
    return json.loads((PUB/'web/assets/higgsfield-summary.json').read_text(encoding='utf-8'))['validation']['manual_events']

def event_agreement(events,refs,tolerance=0):
    # Maximum bipartite cardinality: overlapping same-direction windows cannot reuse an event.
    edges={i:sorted([j for j,r in enumerate(refs) if e['direction']==r['direction'] and r['window_seconds'][0]-tolerance-1e-8<=e['timestamp']<=r['window_seconds'][1]+tolerance+1e-8],key=lambda j:abs(e['timestamp']-sum(refs[j]['window_seconds'])/2)) for i,e in enumerate(events)}
    assigned={}
    def augment(i,seen):
        for j in edges[i]:
            if j in seen:continue
            seen.add(j)
            if j not in assigned or augment(assigned[j],seen):assigned[j]=i;return True
        return False
    for i in range(len(events)):augment(i,set())
    pairs=[{'reference':refs[j].get('manual_id',refs[j].get('subject',str(j))),'track_id':events[i]['track_id'],'timestamp':events[i]['timestamp'],'direction':events[i]['direction'],'window_seconds':refs[j]['window_seconds']} for j,i in sorted(assigned.items())]
    return {'matched':len(assigned),'reference_events':len(refs),'predicted_events':len(events),'unmatched_predictions':len(events)-len(assigned),'unmatched_references':len(refs)-len(assigned),'tolerance_seconds':tolerance,'pairs':pairs,'scope':'Direction/time-only one-to-one agreement with AI source review; not identity-verified accuracy.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['yolo','rfdetr','deim'],default='yolo')
    parser.add_argument('--tracker',choices=['bytetrack','tracktrack','tracktrack-reid'],default='bytetrack')
    parser.add_argument('--clip',choices=['crowd','two-person'],required=True)
    parser.add_argument('--cache',help='Completed pipeline repNN/tracks.jsonl. Detection is excluded when supplied.')
    parser.add_argument('--output',help='Repository-relative output directory; default runs/<engine>-<tracker>-<clip>. Must not already exist.')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--max-frames',type=int,default=0)
    args=parser.parse_args()
    protocol=json.loads(Path(__file__).with_name('protocol.json').read_text())
    spec=protocol['sources'][args.clip];source=PUB/spec['file'];assert sha(source)==spec['sha256']
    cfg=json.loads((PUB/'visioneye/config.json').read_text())
    out=PUB/(args.output or f'runs/{args.engine}-{args.tracker}-{args.clip}');out.mkdir(parents=True,exist_ok=False)
    if args.cache:args.cache=str(PUB/args.cache)
    lock=RUNTIME/'gpu.lock'
    fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        if args.cache:
            cache=[json.loads(x) for x in Path(args.cache).read_text().splitlines()]
            cache_summary=json.loads(Path(args.cache).with_name('summary.json').read_text())
            assert cache_summary['source_sha256']==spec['sha256'] and len(cache)==spec['frames']
            engine=None;engine_meta={'model':'Cached YOLO26n boxes','cache_sha256':sha(args.cache),'origin':cache_summary['engine_metadata']}
        else:
            tick=time.perf_counter();engine=importlib.import_module(args.engine+'_adapter').DetectorAdapter(device='cuda:0');sync()
            load_seconds=time.perf_counter()-tick;engine_meta=safe_meta(engine.metadata)
        from tracker_adapter import TrackerAdapter
        results=[]
        for rep in range(1,args.repeats+1):
            target=out/f'rep{rep:02}';target.mkdir()
            cap=cv2.VideoCapture(str(source));assert cap.isOpened()
            ok,first=cap.read();assert ok
            fps=cap.get(cv2.CAP_PROP_FPS);assert abs(fps-spec['fps'])<1e-6
            tick=time.perf_counter();tracker=TrackerAdapter(args.tracker,fps,device='0');sync();tracker_load_seconds=time.perf_counter()-tick
            warm_tick=time.perf_counter()
            for _ in range(protocol['warmup_calls']):
                raw=engine.process(first) if engine else cache[0]['detections']
                tracker.process(first,raw)
            sync();warm_seconds=time.perf_counter()-warm_tick;tracker.reset();cap.release();cap=cv2.VideoCapture(str(source))
            torch.cuda.reset_peak_memory_stats();probe=GPUProbe();probe.start()
            counter=DirectionalCounter(((128,396),(1152,396)),in_side=1,hysteresis=8,initial_occupancy=0,max_gap_frames=15,ttl_frames=120)
            stages={k:[] for k in ['source_read','detector','tracker','counter','telemetry','processing']}
            all_events=[];ids=set();obs=0;counts=[];index=0;run_tick=time.perf_counter()
            with (target/'tracks.jsonl').open('w',encoding='utf-8') as f:
                while True:
                    begin=tick=time.perf_counter();ok,frame=cap.read();read_elapsed=time.perf_counter()-tick
                    if not ok:break
                    assert frame.shape[:2]==(720,1280)
                    stages['source_read'].append(read_elapsed)
                    sync();tick=time.perf_counter()
                    raw=engine.process(frame) if engine else cache[index]['detections']
                    sync()
                    if engine:stages['detector'].append(time.perf_counter()-tick)
                    tick=time.perf_counter();detections=tracker.process(frame,raw);sync();stages['tracker'].append(time.perf_counter()-tick)
                    tick=time.perf_counter();points={};geometry=[]
                    for d in detections:
                        box=[float(v) for v in d['xyxy']];assert len(box)==4 and np.isfinite(box).all() and box[2]>box[0] and box[3]>box[1]
                        foot=[(box[0]+box[2])/2,box[3]];ident=d['track_id'];ident=None if ident is None else int(ident)
                        if ident is not None:
                            if ident in points:raise ValueError('Same track assigned to multiple boxes')
                            points[ident]=tuple(foot)
                        geometry.append({'xyxy':box,'confidence':float(d['confidence']),'track_id':ident,'footpoint_px':foot,'signed_gate_distance_px':foot[1]-396})
                    events=counter.update(points,index,index/fps);state={**counter.stats(),'visible':len(points)}
                    ids.update(points);obs+=len(detections);counts.append(len(detections));all_events.extend(events);stages['counter'].append(time.perf_counter()-tick)
                    tick=time.perf_counter();f.write(json.dumps({'frame':index,'timestamp':index/fps,'detections':geometry,'detection_count':len(detections),'confirmed_track_count':len(points),'events':events,'stats':state},separators=(',',':'),allow_nan=False)+'\n');stages['telemetry'].append(time.perf_counter()-tick)
                    stages['processing'].append(time.perf_counter()-begin);index+=1
                    if args.max_frames and index>=args.max_frames:break
            cap.release();run_seconds=time.perf_counter()-run_tick;gpu=probe.finish()
            if not args.max_frames:assert index==spec['frames']
            with (target/'events.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=['track_id','direction','frame','timestamp']);writer.writeheader();writer.writerows(all_events)
            summary={'mode':args.engine+'-'+args.tracker,'status':'completed' if index==spec['frames'] else 'frame_limit','comparison_kind':'cached-tracker' if args.cache else 'detector-pipeline','clip':args.clip,'repeat':rep,'processed_frames':index,'source_fps':fps,'input_size_px':[1280,720],'source_sha256':spec['sha256'],'recording_start_seconds':0,'config':cfg,'privacy':'transparent_overlay','occupancy_ground_truth_available':False,**counter.stats(),'confirmed_tracks':len(ids),'confirmed_track_ids':sorted(ids),'detector_count':obs,'detection_counts':{'min':min(counts),'median':float(np.median(counts)),'max':max(counts)},'processing_seconds':sum(stages['processing']),'processing_fps':round(index/sum(stages['processing']),2),'wall_seconds':run_seconds,'model_initialization_seconds':load_seconds if engine and rep==1 else None,'tracker_initialization_seconds':tracker_load_seconds,'warmup_seconds':warm_seconds,'warmup_calls':protocol['warmup_calls'],'stage_elapsed':{k:stats(v) for k,v in stages.items()},'gpu_memory':{**gpu,'torch_peak_allocated_mib':round(torch.cuda.max_memory_allocated()/1048576,1),'torch_peak_reserved_mib':round(torch.cuda.max_memory_reserved()/1048576,1)},'engine_metadata':engine_meta,'tracker_metadata':safe_meta(tracker.metadata),'package_versions':{'torch':torch.__version__,'numpy':np.__version__,'opencv':cv2.__version__},'python_version':platform.python_version(),'protocol_sha256':sha(Path(__file__).with_name('protocol.json')),'runner_sha256':sha(__file__),'event_agreement':{'strict':event_agreement(all_events,references(args.clip)), 'plus_0_5s':event_agreement(all_events,references(args.clip),.5)},'measurement_notes':[protocol['timing'],protocol['ground_truth']]}
            (target/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');results.append(summary)
            print(json.dumps({'repeat':rep,'engine':args.engine,'tracker':args.tracker,'clip':args.clip,'frames':index,'IN':counter.total_in,'OUT':counter.total_out,'ids':len(ids),'fps':summary['processing_fps'],'event_strict':summary['event_agreement']['strict']['matched'],'event_05':summary['event_agreement']['plus_0_5s']['matched']},ensure_ascii=True),flush=True)
            del tracker
        (out/'aggregate.json').write_text(json.dumps({'protocol':protocol,'results':results},ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    finally:
        lock.unlink(missing_ok=True)

if __name__=='__main__':main()
