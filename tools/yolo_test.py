"""Optional genuine CPU inference; no downloads, known licensed local scene."""
import argparse
import json
import statistics
import time
import cv2
from services.camera_sim.scene import render
from services.cv_detector.yolo import Settings, load_model, parse_results, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default=None)
    parser.add_argument('--image',help='Optional local test image; default is the local person-zone compositor')
    parser.add_argument('--runs',type=int,default=10)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    settings = Settings.from_env()
    if args.model:
        from dataclasses import replace
        settings = replace(settings,model=args.model)
    frame = cv2.imread(args.image) if args.image else render(40,'person-zone')
    if frame is None:
        raise ValueError('Cannot decode local test image')
    model = load_model(settings)
    latencies = []
    cpu_started = time.process_time()
    started = time.perf_counter()
    for i in range(args.runs+1):
        tick = time.perf_counter()
        results = model.predict(frame,device='cpu',conf=settings.confidence,imgsz=640,verbose=False,save=False)
        detections = parse_results(results,frame.shape[1],frame.shape[0],settings.confidence)
        if i:
            latencies.append(time.perf_counter()-tick)
    assert detections, 'No genuine supported detection on the local test image'
    payload, safety = messages(detections,settings,frame.shape[1],frame.shape[0],time.time(),time.time())
    if not args.image:
        assert safety, 'Person-zone image did not produce a genuine restricted-zone person detection'
    print(json.dumps({'model':settings.model,'classes':model.names,'detections':payload['detections'],
                      'safety_events':safety,'runs':args.runs,'warm_mean_ms':1000*statistics.mean(latencies),
                      'warm_min_ms':1000*min(latencies),'warm_max_ms':1000*max(latencies),
                      'process_cpu_seconds':time.process_time()-cpu_started,
                      'wall_seconds':time.perf_counter()-started},indent=2))


if __name__ == '__main__':
    main()
