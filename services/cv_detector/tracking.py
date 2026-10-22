"""CPU tracking: class-gated global assignment with constant-velocity prediction.

Tracks are camera-local. This is not cross-camera re-identification. No model or
simulator state enters the tracker: only image-inferred boxes and capture times.
"""
from collections import deque
from dataclasses import dataclass, field
import math
import numpy as np
from scipy.optimize import linear_sum_assignment
from services.cv_detector.yolo import overlaps

PRODUCTS = {'bottle', 'cup', 'package', 'backpack', 'suitcase', 'handbag'}


def centre(box):
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)


@dataclass
class Track:
    id: int
    kind: str
    bbox: list
    confidence: float
    first: float
    last: float
    hits: int = 1
    vx: float = 0
    vy: float = 0
    counted: bool = False
    zone_since: float | None = None
    person_since: float | None = None
    person_notified: float = 0
    wrong_since: float | None = None
    states: set = field(default_factory=set)
    history: deque = field(default_factory=lambda: deque(maxlen=600))


class Tracker:
    def __init__(self, camera, zone=(.60,.16,.98,.86), counting_x=320,
                 stalled_seconds=5, dwell_seconds=13, ttl=2):
        self.camera, self.zone, self.line = camera, zone, counting_x
        self.stalled_seconds, self.dwell_seconds, self.ttl = stalled_seconds, dwell_seconds, ttl
        self.tracks, self.next_id = {}, 1
        self.count = 0
        self.last_timestamp = None

    def reset(self):
        # Preserve count and next ID through RTSP loss; discard motion history.
        self.tracks.clear()
        self.last_timestamp = None

    def update(self, detections, timestamp, conveyor_moving=True, width=640, height=360):
        if not math.isfinite(timestamp) or (self.last_timestamp is not None and timestamp <= self.last_timestamp):
            return [], []
        self.last_timestamp = timestamp
        events = []
        for tid, track in list(self.tracks.items()):
            if timestamp-track.last > self.ttl:
                if track.person_since is not None:
                    events.append(self.event('person_in_restricted_zone', track, timestamp,
                                             state='EXITED', duration=track.last-track.person_since))
                del self.tracks[tid]
        existing = list(self.tracks.values())
        matches = {}
        if existing and detections:
            costs = np.full((len(existing),len(detections)),1e6)
            for i,track in enumerate(existing):
                x,y = centre(track.bbox)
                dt = min(timestamp-track.last, self.ttl)
                for j,d in enumerate(detections):
                    if track.kind != d['class']:
                        continue
                    a,b = centre(d['bbox'])
                    distance = math.hypot(a-x-track.vx*dt, b-y-track.vy*dt)
                    if distance < 100:
                        costs[i,j] = distance
            rows, columns = linear_sum_assignment(costs)
            for i,j in zip(rows,columns):
                if costs[i,j] < 100:
                    matches[j] = existing[i]
        output = []
        for j,detection in enumerate(detections):
            if j in matches:
                track = matches[j]
                px,py = centre(track.bbox)
                x,y = centre(detection['bbox'])
                dt = timestamp-track.last
                track.vx = .5*track.vx+.5*(x-px)/dt
                track.vy = .5*track.vy+.5*(y-py)/dt
                track.hits += 1
                previous_x = px
            else:
                track = Track(self.next_id,detection['class'],detection['bbox'],
                              detection['confidence'],timestamp,timestamp)
                self.next_id += 1
                self.tracks[track.id] = track
                previous_x = centre(track.bbox)[0]
            track.bbox, track.confidence, track.last = detection['bbox'],detection['confidence'],timestamp
            x,y = centre(track.bbox)
            track.history.append((timestamp,x,y))
            while len(track.history)>1 and timestamp-track.history[1][0] > self.stalled_seconds:
                track.history.popleft()
            confirmed = track.hits >= 2
            product = track.kind in PRODUCTS
            if confirmed and product and not track.counted and previous_x < self.line <= x and track.vx > 0:
                track.counted = True
                self.count += 1
                events.append(self.event('product_crossed',track,timestamp,count=self.count))
            inside = overlaps(track.bbox,(.25,.30,.78,.76),width,height)
            if inside and product:
                if track.zone_since is None:
                    track.zone_since = timestamp
                    events.append(self.event('inspection_zone',track,timestamp,state='ENTERED'))
            elif track.zone_since is not None:
                events.append(self.event('inspection_zone',track,timestamp,state='EXITED',
                                         duration=timestamp-track.zone_since))
                track.zone_since = None
            stationary = (confirmed and product and inside and conveyor_moving and len(track.history)>2
                          and timestamp-track.history[0][0] >= self.stalled_seconds-.1
                          and max(p[1] for p in track.history)-min(p[1] for p in track.history)<14
                          and max(p[2] for p in track.history)-min(p[2] for p in track.history)<14)
            if confirmed and product and track.vx < -12:
                track.wrong_since = track.wrong_since if track.wrong_since is not None else timestamp
            else:
                track.wrong_since = None
            states = set()
            if stationary:
                states.add('object_stalled')
            if track.wrong_since is not None and timestamp-track.wrong_since >= 2:
                states.add('wrong_direction')
            if track.zone_since is not None and timestamp-track.zone_since > self.dwell_seconds:
                states.add('excessive_dwell')
            person_inside = confirmed and track.kind=='person' and overlaps(track.bbox,self.zone,width,height)
            if person_inside:
                entered = track.person_since is None
                track.person_since = timestamp if entered else track.person_since
                states.add('person_in_restricted_zone')
                if entered:
                    events.append(self.event('person_in_restricted_zone',track,timestamp,state='ENTERED'))
                    track.person_notified = timestamp
                elif timestamp-track.person_notified>=5:
                    events.append(self.event('person_in_restricted_zone',track,timestamp,state='PRESENT',
                                             duration=timestamp-track.person_since))
                    track.person_notified = timestamp
            elif track.person_since is not None:
                events.append(self.event('person_in_restricted_zone',track,timestamp,state='EXITED',
                                         duration=timestamp-track.person_since))
                track.person_since = None
            for state in states-track.states:
                if state != 'person_in_restricted_zone':
                    events.append(self.event(state,track,timestamp,state='ACTIVE',duration=timestamp-track.first))
            for state in track.states-states:
                if state != 'person_in_restricted_zone':
                    events.append(self.event(state,track,timestamp,state='CLEARED'))
            track.states = states
            if confirmed:
                output.append({**detection,'track_id':track.id,'direction':'reverse' if track.vx < -12 else
                               ('forward' if track.vx > 12 else 'stationary'),
                               'speed_px_per_second':round(math.hypot(track.vx,track.vy),2),
                               'velocity':[round(track.vx,2),round(track.vy,2)],
                               'time_visible_seconds':round(timestamp-track.first,2),
                               'dwell_seconds':round(timestamp-track.zone_since,2) if track.zone_since is not None else 0,
                               'restricted_dwell_seconds':round(timestamp-track.person_since,2) if track.person_since is not None else 0,
                               'restricted_state':'PRESENT' if person_inside else None,
                               'states':sorted(states)})
        return output, events

    def event(self, name, track, timestamp, state=None, duration=0, **extra):
        return dict(camera=self.camera,event=name,track_id=track.id,site='local',line='line1',
                    timestamp=timestamp,source_timestamp=timestamp,duration_seconds=round(duration,3),
                    **({'state':state} if state else {}),**extra)
