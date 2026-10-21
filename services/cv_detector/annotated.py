"""Optional HTTP preview: a single latest JPEG, with stale-frame expiry."""
import asyncio
import threading
import time
import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
import uvicorn


def label(image, text, x, y, color):
    (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .4, 1)
    x = max(0, min(x, image.shape[1]-width-8))
    y = max(height+5, min(y, image.shape[0]-baseline-4))
    cv2.rectangle(image, (x,y-height-4), (x+width+7,y+baseline+3), (25,32,36), -1)
    cv2.putText(image,text,(x+3,y),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1,cv2.LINE_AA)


class Preview:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.lock = threading.Lock()
        self.jpeg = None
        self.updated = 0
        self.server = None
        self.thread = None

    def update(self, frame, reasons, worker):
        if not self.enabled:
            return
        image = frame.copy()
        latest = worker.snapshot()
        if worker.enabled and worker.settings:
            h, w = image.shape[:2]
            a,b,c,d = worker.settings.zone
            cv2.rectangle(image,(round(a*w),round(b*h)),(round(c*w),round(d*h)),(80,200,235),2)
            label(image,'RESTRICTED / DEMO',round(a*w),max(54,round(b*h)-4),(80,200,235))
        if latest:
            for obj in latest['detections']:
                x1,y1,x2,y2 = obj['bbox']
                cv2.rectangle(image,(x1,y1),(x2,y2),(130,230,110),2)
                label(image,f"{obj['class']} {obj['confidence']:.2f}",x1,max(62,y1-5),(130,230,110))
        state = 'OFF' if not worker.enabled else (f"{time.time()-latest['source_timestamp']:.1f}s old" if latest else 'waiting / stale')
        cv2.rectangle(image,(0,293),(image.shape[1],314),(25,32,36),-1)
        cv2.putText(image,'OpenCV: '+(', '.join(reasons) or 'normal')+' | YOLO: '+state,
                    (14,309),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1,cv2.LINE_AA)
        ok, jpeg = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,82])
        if ok:
            with self.lock:
                self.jpeg, self.updated = jpeg.tobytes(), time.monotonic()

    def invalidate(self):
        with self.lock:
            self.jpeg = None

    def current(self):
        with self.lock:
            return self.jpeg if time.monotonic()-self.updated < 3 else None

    def app(self):
        app = FastAPI(title='Local CV preview')

        @app.get('/healthz')
        def health():
            # Liveness is independent of stream availability and optional YOLO.
            return {'status':'ok', 'stream_fresh': self.current() is not None}

        @app.get('/snapshot.jpg')
        def snapshot():
            jpeg = self.current()
            if jpeg is None:
                raise HTTPException(503,'No recent decoded frame')
            return Response(jpeg,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

        @app.get('/annotated.mjpg')
        async def stream():
            async def frames():
                while True:
                    jpeg = self.current()
                    if jpeg:
                        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg+b'\r\n'
                    await asyncio.sleep(.1)
            return StreamingResponse(frames(),media_type='multipart/x-mixed-replace; boundary=frame',
                                     headers={'Cache-Control':'no-store'})
        return app

    def start(self):
        # Keep liveness available even when annotation is switched off.
        self.server = uvicorn.Server(uvicorn.Config(self.app(),host='0.0.0.0',port=8083,log_level='warning'))
        self.thread = threading.Thread(target=self.server.run,name='cv-preview',daemon=True)
        self.thread.start()

    def close(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=3)
