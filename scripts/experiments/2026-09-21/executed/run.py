"""Source-locked robustness comparisons, one GPU job at a time."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, platform, re, sys, threading, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUB = ROOT / 'outputs/visioneye-repo'
RUNTIME = HERE / '.runtime'
RUNTIME.mkdir(exist_ok=True)
sys.path.insert(0, str(PUB / 'visioneye'))
os.environ.setdefault('YOLO_CONFIG_DIR', str(RUNTIME / 'ultralytics'))
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
import cv2, numpy as np, torch
from analytics import DirectionalCounter

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def dump(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
def safe(value):
    if isinstance(value, dict): return {k:safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [safe(v) for v in value]
    if isinstance(value, Path): return value.name
    if isinstance(value, str) and re.match(r'^[A-Za-z]:[\\/]', value): return Path(value).name
    return value
def sync(): torch.cuda.synchronize()
def stats(values):
    return {'calls':len(values), 'total_seconds':round(sum(values),6), 'p50_ms':round(float(np.median(values))*1000,3), 'p95_ms':round(float(np.percentile(values,95))*1000,3)} if values else None

def match_events(events, refs, tolerance=0):
    edges={i:sorted([j for j,r in enumerate(refs) if e['direction']==r['direction'] and r['window_seconds'][0]-tolerance-1e-8 <= e['timestamp'] <= r['window_seconds'][1]+tolerance+1e-8], key=lambda j:abs(e['timestamp']-sum(refs[j]['window_seconds'])/2)) for i,e in enumerate(events)}
    assigned={}
    def augment(i,seen):
        for j in edges[i]:
            if j in seen: continue
            seen.add(j)
            if j not in assigned or augment(assigned[j],seen): assigned[j]=i; return True
        return False
    for i in range(len(events)): augment(i,set())
    pairs=[{'reference':refs[j]['manual_id'], 'track_id':events[i]['track_id'], 'timestamp':events[i]['timestamp'], 'direction':events[i]['direction'], 'window_seconds':refs[j]['window_seconds']} for j,i in sorted(assigned.items())]
    return {'matched':len(pairs), 'reference_events':len(refs), 'predicted_events':len(events), 'unmatched_predictions':len(events)-len(pairs), 'unmatched_references':len(refs)-len(pairs), 'tolerance_seconds':tolerance, 'pairs':pairs, 'scope':'Clip/direction/time-only one-to-one agreement with source-only AI review. Not identity-verified accuracy; ambiguous source events excluded from references, retained in source review.'}

class GPUProbe:
    def __init__(self): self.samples=[]; self.stop=threading.Event(); self.thread=None
    def start(self):
        try:
            import pynvml
            pynvml.nvmlInit(); handle=pynvml.nvmlDeviceGetHandleByIndex(0)
            def sample():
                while not self.stop.is_set():
                    try: self.samples.append((pynvml.nvmlDeviceGetMemoryInfo(handle).used/1048576,pynvml.nvmlDeviceGetUtilizationRates(handle).gpu))
                    except Exception: pass
                    self.stop.wait(.1)
            self.thread=threading.Thread(target=sample,daemon=True); self.thread.start()
        except Exception: pass
    def finish(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=1)
        return {'device_used_peak_mib':round(max(x[0] for x in self.samples),1) if self.samples else None, 'device_utilization_mean_percent':round(float(np.mean([x[1] for x in self.samples])),1) if self.samples else None, 'sample_count':len(self.samples), 'scope':'Whole-device 100ms samples, including display and other processes; not isolated model memory.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['yolo26n','yolov8n','yolo11n','rtdetrv2_s'],default='yolo26n')
    parser.add_argument('--tracker',choices=['bytetrack','botsort','tracktrack'],default='bytetrack')
    parser.add_argument('--clip',required=True)
    parser.add_argument('--cache',help='YOLO26n rep01/tracks.jsonl; detection excluded')
    parser.add_argument('--output',required=True)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--max-frames',type=int,default=0)
    args=parser.parse_args()
    if args.repeats<1: parser.error('repeats must be positive')
    protocol=load(HERE/'protocol.json'); spec=protocol['sources'][args.clip]
    source=PUB/spec['file']; review_path=PUB/spec['review_file']
    if sha(source)!=spec['sha256'] or sha(review_path)!=spec['review_sha256']: raise ValueError('Source or locked review hash changed')
    review=load(review_path)
    if review['source_sha256']!=spec['sha256'] or review['model_outputs_seen'] is not False: raise ValueError('Source-only review contract failed')
    refs=review['manual_events']
    if not torch.cuda.is_available(): raise RuntimeError('CUDA is required for this measured protocol')
    torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
    torch.set_float32_matmul_precision('highest')
    cv2.setNumThreads(2)
    out=Path(args.output); out.mkdir(parents=True,exist_ok=False)
    lock=RUNTIME/'gpu.lock'; fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.write(fd,str(os.getpid()).encode()); os.close(fd)
    try:
        if args.cache:
            cache=[json.loads(x) for x in Path(args.cache).read_text().splitlines()]
            cached=load(Path(args.cache).with_name('summary.json'))
            if cached['source_sha256']!=spec['sha256'] or len(cache)!=spec['frames'] or cached['engine_metadata']['model'].lower()!='yolo26n': raise ValueError('Cache input contract failed')
            engine=None; engine_meta={'model':'YOLO26n FP32 cached boxes','cache_sha256':sha(args.cache),'origin':cached['engine_metadata']}
            load_seconds=None
        else:
            tick=time.perf_counter()
            if args.engine=='rtdetrv2_s':
                from rtdetr_adapter import DetectorAdapter
                engine=DetectorAdapter(device='cuda:0')
            else:
                from baseline_adapter import DetectorAdapter
                engine=DetectorAdapter(model=args.engine,device='cuda:0')
            sync(); load_seconds=time.perf_counter()-tick; engine_meta=safe(engine.metadata)
        from baseline_adapter import TrackerAdapter
        results=[]
        width,height=spec['width'],spec['height']; line=protocol['line_px']
        cfg={'line':protocol['line_normalized'],'in_side':1,'floor_quad':None,'initial_occupancy':0,'hysteresis_px':8.,'max_gap_frames':15,'privacy':'none'}
        for rep in range(1,args.repeats+1):
            target=out/f'rep{rep:02}'; target.mkdir()
            cap=cv2.VideoCapture(str(source)); ok,first=cap.read()
            if not ok: raise ValueError('Unreadable source')
            fps=cap.get(cv2.CAP_PROP_FPS)
            if abs(fps-spec['fps'])>1e-6: raise ValueError('FPS mismatch')
            tick=time.perf_counter(); tracker=TrackerAdapter(args.tracker,fps,device='0'); sync(); tracker_load=time.perf_counter()-tick
            warm=time.perf_counter()
            for _ in range(protocol['warmup_calls']): tracker.process(first,engine.process(first) if engine else cache[0]['detections'])
            sync(); warm_seconds=time.perf_counter()-warm; tracker.reset(); cap.release(); cap=cv2.VideoCapture(str(source))
            torch.cuda.reset_peak_memory_stats(); probe=GPUProbe(); probe.start()
            counter=DirectionalCounter(tuple(map(tuple,line)),in_side=1,hysteresis=8,initial_occupancy=0,max_gap_frames=15,ttl_frames=120)
            stages={k:[] for k in ['source_read','detector','tracker','counter','telemetry','processing']}
            all_events=[]; ids=set(); counts=[]; index=0; run_tick=time.perf_counter()
            with (target/'tracks.jsonl').open('w',encoding='utf-8') as stream:
                while True:
                    begin=tick=time.perf_counter(); ok,frame=cap.read(); read_elapsed=time.perf_counter()-tick
                    if not ok: break
                    if frame.shape[:2]!=(height,width): raise ValueError('Source dimensions changed')
                    stages['source_read'].append(read_elapsed); sync(); tick=time.perf_counter()
                    raw=engine.process(frame) if engine else cache[index]['detections']; sync()
                    if engine: stages['detector'].append(time.perf_counter()-tick)
                    tick=time.perf_counter(); detections=tracker.process(frame,raw); sync(); stages['tracker'].append(time.perf_counter()-tick)
                    tick=time.perf_counter(); points={}; geometry=[]
                    for d in detections:
                        box=[float(v) for v in d['xyxy']]
                        if len(box)!=4 or not np.isfinite(box).all() or box[2]<=box[0] or box[3]<=box[1]: raise ValueError('Invalid detection')
                        foot=[(box[0]+box[2])/2,box[3]]; ident=None if d['track_id'] is None else int(d['track_id'])
                        if ident is not None:
                            if ident in points: raise ValueError('Duplicate track ID within frame')
                            points[ident]=tuple(foot)
                        geometry.append({'xyxy':box,'confidence':float(d['confidence']),'track_id':ident,'footpoint_px':foot,'signed_gate_distance_px':foot[1]-line[0][1]})
                    events=counter.update(points,index,index/fps); state={**counter.stats(),'visible':len(points)}
                    ids.update(points); counts.append(len(detections)); all_events.extend(events); stages['counter'].append(time.perf_counter()-tick)
                    tick=time.perf_counter(); stream.write(json.dumps({'frame':index,'timestamp':index/fps,'detections':geometry,'detection_count':len(detections),'confirmed_track_count':len(points),'events':events,'stats':state},separators=(',',':'),allow_nan=False)+'\n'); stages['telemetry'].append(time.perf_counter()-tick)
                    stages['processing'].append(time.perf_counter()-begin); index+=1
                    if args.max_frames and index>=args.max_frames: break
            cap.release(); wall=time.perf_counter()-run_tick; gpu=probe.finish()
            if not args.max_frames and index!=spec['frames']: raise ValueError('Frame count mismatch')
            with (target/'events.csv').open('w',newline='',encoding='utf-8') as stream:
                writer=csv.DictWriter(stream,fieldnames=['track_id','direction','frame','timestamp']); writer.writeheader(); writer.writerows(all_events)
            summary={'mode':args.engine+'-'+args.tracker,'status':'completed' if index==spec['frames'] else 'frame_limit','comparison_kind':'cached-tracker' if args.cache else 'detector-pipeline','clip':args.clip,'repeat':rep,'processed_frames':index,'source_fps':fps,'input_size_px':[width,height],'source_sha256':spec['sha256'],'recording_start_seconds':0,'config':cfg,'privacy':'transparent_overlay','occupancy_ground_truth_available':False,**counter.stats(),'confirmed_tracks':len(ids),'confirmed_track_ids':sorted(ids),'detector_count':sum(counts),'detection_counts':{'min':min(counts),'median':float(np.median(counts)),'max':max(counts)},'processing_seconds':sum(stages['processing']),'processing_fps':round(index/sum(stages['processing']),2),'wall_seconds':wall,'model_initialization_seconds':load_seconds if engine and rep==1 else None,'tracker_initialization_seconds':tracker_load,'warmup_seconds':warm_seconds,'warmup_calls':protocol['warmup_calls'],'stage_elapsed':{k:stats(v) for k,v in stages.items()},'gpu_memory':{**gpu,'torch_peak_allocated_mib':round(torch.cuda.max_memory_allocated()/1048576,1),'torch_peak_reserved_mib':round(torch.cuda.max_memory_reserved()/1048576,1)},'engine_metadata':safe(engine.metadata) if engine else engine_meta,'tracker_metadata':safe(tracker.metadata),'package_versions':{'torch':torch.__version__,'numpy':np.__version__,'opencv':cv2.__version__},'python_version':platform.python_version(),'protocol_sha256':sha(HERE/'protocol.json'),'source_review_sha256':sha(review_path),'runner_sha256':sha(__file__),'event_agreement':{'strict':match_events(all_events,refs),'plus_0_5s':match_events(all_events,refs,.5)},'measurement_notes':protocol['measurement_notes'],'reproducibility':{'source_sha256':spec['sha256'],'source_path':spec['file']}}
            dump(target/'summary.json',summary); results.append(summary)
            print(json.dumps({'repeat':rep,'engine':args.engine,'tracker':args.tracker,'clip':args.clip,'frames':index,'IN':counter.total_in,'OUT':counter.total_out,'IDs':len(ids),'fps':summary['processing_fps'],'strict':summary['event_agreement']['strict']['matched'],'expanded':summary['event_agreement']['plus_0_5s']['matched'],'refs':len(refs)}),flush=True)
            del tracker
        dump(out/'aggregate.json',{'protocol':protocol,'results':results})
    finally: lock.unlink(missing_ok=True)

if __name__=='__main__': main()
