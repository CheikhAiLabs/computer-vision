"""Image-only quality checks and explicit, reset-aware production analytics."""
from collections import deque
import math
import cv2
import numpy as np


def inspect_markers(frame):
    """Known cyan fiducials: classical marker segmentation, never a YOLO defect class.

    Horizontal inspection marks (aspect >5) indicate an orientation defect in
    this demonstration. Ordinary parcel marks define a known 52x52 inspection ROI.
    """
    hsv = cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,np.array((80,130,90)),np.array((105,255,255)))
    mask[:120] = 0
    mask[313:] = 0
    contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    detections, defects = [], []
    for contour in contours:
        x,y,w,h = cv2.boundingRect(contour)
        if w<12 or h<3 or cv2.contourArea(contour)<40:
            continue
        if w/h > 5:
            defects.append({'reason':'product-marker-outside-conveyor' if y>275 else 'orientation-marker-horizontal','bbox':[x,y,x+w,y+h],
                            'aspect_ratio':round(w/h,2),'method':'OpenCV cyan fiducial geometry'})
        elif 1.3 < w/h < 4:
            detections.append({'class':'package','confidence':1.0,
                               'bbox':[max(0,x-12),max(120,y-7),min(640,x+40),min(280,y+45)],
                               'method':'OpenCV inspection marker; confidence is deterministic presence'})
    return detections, defects


class Reconciliation:
    def __init__(self, tolerance=3, hold=15, missing_seconds=45, min_transit_seconds=20):
        if tolerance<0 or not all(math.isfinite(x) and x>0 for x in (hold,missing_seconds)):
            raise ValueError('Invalid reconciliation settings')
        self.tolerance,self.hold,self.missing_seconds = tolerance,hold,missing_seconds
        self.min_transit_seconds = min_transit_seconds
        self.baseline = None
        self.previous_plc = None
        self.exceeded_since = None
        self.pending = deque(maxlen=1000)
        self.last_entered = self.last_exited = 0
        self.epoch = 0
        self.paused = False

    def reset(self):
        self.baseline = None
        self.previous_plc = None
        self.exceeded_since = None
        self.pending.clear()

    def update(self, plc, entered, exited, timestamp, fresh=True):
        if plc is not None and (not isinstance(plc,(int,float)) or not math.isfinite(plc) or plc<0):
            raise ValueError('Invalid PLC count')
        new_entry = max(0,entered-self.last_entered)
        new_exit = max(0,exited-self.last_exited)
        self.last_entered,self.last_exited = entered,exited
        for _ in range(min(new_entry,1000)):
            self.pending.append(timestamp)
        for _ in range(min(new_exit,len(self.pending))):
            # Ignore exits from pre-existing startup stock until a newly observed
            # entry could physically reach exit (nominal transit is 22.4 seconds).
            if timestamp-self.pending[0] >= self.min_transit_seconds:
                self.pending.popleft()
        if not fresh or plc is None:
            self.baseline = None
            self.exceeded_since = None
            self.pending.clear()
            return dict(ready=False,difference=None,mismatch=False,in_process=None,missing_exit=False,epoch=self.epoch)
        if self.baseline is None or (self.previous_plc is not None and plc<self.previous_plc):
            self.baseline = (plc,entered)
            self.exceeded_since = None
            self.epoch += 1
        self.previous_plc = plc
        difference = int((plc-self.baseline[0])-(entered-self.baseline[1]))
        if abs(difference)>self.tolerance:
            self.exceeded_since = timestamp if self.exceeded_since is None else self.exceeded_since
        else:
            self.exceeded_since = None
        return dict(ready=True,difference=difference,
                    mismatch=self.exceeded_since is not None and timestamp-self.exceeded_since>=self.hold,
                    in_process=len(self.pending),missing_exit=bool(self.pending and timestamp-self.pending[0]>self.missing_seconds),
                    epoch=self.epoch)


def health_score(signals):
    """Weights total 100. Unknown inputs lose their weight; no synthetic healthy data."""
    weights = {'plc':15,'conveyor':10,'temperature':10,'vibration':10,'quality':10,
               'opencv':10,'yolo':10,'cameras':10,'ml':5,'network':10}
    components = {name:{'healthy':signals.get(name),'weight':weight,
                        'earned':weight if signals.get(name) is True else 0} for name,weight in weights.items()}
    return sum(v['earned'] for v in components.values()),components
