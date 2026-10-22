"""Offline tests for real tracking math, image inspection and derived signals."""
import json
import time
import threading
import unittest
from unittest.mock import Mock, patch
import cv2
import numpy as np
from prometheus_client import CollectorRegistry
from fastapi.testclient import TestClient
from common.line import CAMERAS, sensor_index
from services.camera_sim.scene import render, SCENARIOS
from services.cv_detector.tracking import Tracker
from services.cv_detector.analytics import Reconciliation, health_score, inspect_markers
from services.cv_detector.multicamera import Hub, SharedInference
from services.cv_detector.control_room import create_app
from services.incident_receiver.rules import classify, jam_compatible


def detection(x,y=180,kind='bottle'):
    return dict(bbox=[x-15,y-40,x+15,y+40],confidence=.9,**{'class':kind})


class TrackingTests(unittest.TestCase):
    def test_forward_crossing_counted_once_and_reverse_not_counted(self):
        tracker=Tracker('entry')
        ids=[]
        for i,x in enumerate([250,290,310,330,350,310,330,360]):
            tracks,_=tracker.update([detection(x)],i*.5)
            ids += [t['track_id'] for t in tracks]
        self.assertEqual(set(ids),{1})
        self.assertEqual(tracker.count,1)
        reverse=Tracker('exit')
        for i,x in enumerate([390,350,330,310,290]):
            reverse.update([detection(x)],i*.5)
        self.assertEqual(reverse.count,0)

    def test_global_assignment_preserves_two_different_products(self):
        tracker=Tracker('process')
        tracker.update([detection(100),detection(300,kind='cup')],1)
        tracks,_=tracker.update([detection(320,kind='cup'),detection(120)],1.5)
        self.assertEqual({t['class']:t['track_id'] for t in tracks},{'bottle':1,'cup':2})

    def test_dwell_stall_and_conveyor_state(self):
        tracker=Tracker('process',stalled_seconds=3,dwell_seconds=4)
        events=[]
        for i in range(13):
            tracks,batch=tracker.update([detection(300)],i*.5,True)
            events+=batch
        self.assertIn('object_stalled',tracks[0]['states'])
        self.assertIn('excessive_dwell',tracks[0]['states'])
        self.assertAlmostEqual(tracks[0]['dwell_seconds'],6)
        self.assertEqual(sum(e['event']=='object_stalled' and e['state']=='ACTIVE' for e in events),1)
        tracks,events=tracker.update([detection(300)],6.5,False)
        self.assertNotIn('object_stalled',tracks[0]['states'])
        self.assertTrue(any(e['event']=='object_stalled' and e['state']=='CLEARED' for e in events))

    def test_wrong_direction_requires_sustained_observed_motion(self):
        tracker=Tracker('process')
        for i in range(9):
            tracks,_=tracker.update([detection(500-i*25)],i*.5)
        self.assertIn('wrong_direction',tracks[0]['states'])
        self.assertEqual(tracks[0]['direction'],'reverse')
        self.assertGreater(tracks[0]['speed_px_per_second'],12)

    def test_person_zone_enter_present_exit_and_dwell(self):
        tracker=Tracker('process',zone=(.5,.1,.9,.9))
        tracker.update([detection(400,kind='person')],0)
        tracks,events=tracker.update([detection(400,kind='person')],.5)
        self.assertEqual(events[0]['state'],'ENTERED')
        tracks,events=tracker.update([detection(400,kind='person')],1)
        self.assertIn('person_in_restricted_zone',tracks[0]['states'])
        self.assertEqual(tracks[0]['restricted_dwell_seconds'],.5)
        self.assertFalse(events)
        _,events=tracker.update([],4)
        self.assertEqual(events[0]['state'],'EXITED')
        self.assertEqual(events[0]['duration_seconds'],.5)

    def test_missing_tracks_expire_and_ids_not_reused_after_reset(self):
        tracker=Tracker('entry')
        tracker.update([detection(290)],1)
        tracker.update([detection(330)],1.5)
        self.assertEqual(tracker.count,1)
        tracker.reset()
        tracker.update([detection(250)],3)
        tracks,_=tracker.update([detection(260)],3.5)
        self.assertEqual(tracks[0]['track_id'],2)
        self.assertEqual(tracker.count,1)
        self.assertFalse(tracker.update([],10)[0])

    def test_out_of_order_frame_does_not_corrupt_history(self):
        tracker=Tracker('entry')
        tracker.update([detection(200)],2)
        self.assertEqual(tracker.update([detection(350)],1),([],[]))
        self.assertEqual(tracker.count,0)

    def test_person_never_counted_as_product(self):
        tracker=Tracker('entry')
        for i,x in enumerate((280,300,330,350)):
            tracker.update([detection(x,kind='person')],i)
        self.assertEqual(tracker.count,0)

    def test_event_payload_json_and_scope(self):
        tracker=Tracker('entry')
        tracker.update([detection(290)],1)
        _,events=tracker.update([detection(330)],1.5)
        payload=next(e for e in events if e['event']=='product_crossed')
        self.assertEqual(payload['camera'],'entry')
        self.assertEqual(payload['site'],'local')
        self.assertEqual(payload['line'],'line1')
        self.assertEqual(payload['track_id'],1)
        self.assertEqual(payload['timestamp'],1.5)
        json.dumps(payload,allow_nan=False)


class AnalyticsTests(unittest.TestCase):
    def test_reconciliation_deltas_hold_tolerance_and_plc_reset(self):
        r=Reconciliation(tolerance=2,hold=5)
        self.assertEqual(r.update(100,8,3,0)['difference'],0)
        self.assertFalse(r.update(104,9,3,1)['mismatch'])
        self.assertTrue(r.update(104,9,3,7)['mismatch'])
        self.assertEqual(r.update(104,9,3,7)['difference'],3)
        reset=r.update(0,9,3,8)
        self.assertFalse(reset['mismatch'])
        self.assertEqual(reset['epoch'],2)
        self.assertEqual(reset['difference'],0)

    def test_no_comparison_with_stale_telemetry_and_new_baseline(self):
        r=Reconciliation()
        r.update(100,3,1,0)
        value=r.update(200,4,2,5,False)
        self.assertFalse(value['ready'])
        self.assertIsNone(value['difference'])
        self.assertEqual(r.update(200,4,2,6)['difference'],0)
        self.assertEqual(r.epoch,2)

    def test_aggregate_missing_exit_and_fifo_recovery(self):
        r=Reconciliation(missing_seconds=10,min_transit_seconds=0)
        r.update(0,0,0,0)
        r.update(1,1,0,1)
        self.assertTrue(r.update(1,1,0,12)['missing_exit'])
        value=r.update(1,1,1,13)
        self.assertFalse(value['missing_exit'])
        self.assertEqual(value['in_process'],0)
        r.reset()
        self.assertIsNone(r.baseline)

    def test_startup_exits_cannot_match_new_entries_before_transit(self):
        r=Reconciliation()
        r.update(0,0,0,0)
        r.update(1,1,0,1)
        self.assertEqual(r.update(1,1,1,2)['in_process'],1)
        self.assertEqual(r.update(1,1,2,23)['in_process'],0)

    def test_health_formula_and_unknown_are_explicit(self):
        signals={name:True for name in ('plc','conveyor','temperature','vibration','quality','opencv','yolo','cameras','ml','network')}
        self.assertEqual(health_score(signals)[0],100)
        signals['plc']=False
        signals['network']=None
        score,components=health_score(signals)
        self.assertEqual(score,75)
        self.assertIsNone(components['network']['healthy'])
        self.assertEqual(health_score({})[0],0)

    def test_quality_is_derived_from_marker_pixels(self):
        normal=np.zeros((360,640,3),np.uint8)
        cv2.rectangle(normal,(200,190),(224,200),(220,210,20),-1)
        objects,defects=inspect_markers(normal)
        self.assertEqual(objects[0]['class'],'package')
        self.assertFalse(defects)
        rotated=np.zeros_like(normal)
        cv2.rectangle(rotated,(200,205),(286,211),(220,210,20),-1)
        objects,defects=inspect_markers(rotated)
        self.assertFalse(objects)
        self.assertEqual(defects[0]['reason'],'orientation-marker-horizontal')
        self.assertEqual(inspect_markers(np.zeros_like(normal)),([],[]))

    def test_scene_roles_scenarios_and_recovery(self):
        for scenario in SCENARIOS:
            for camera in CAMERAS:
                image=render(50,scenario,camera,timestamp=1234,scenario_started=1230)
                self.assertEqual(image.shape,(360,640,3))
        self.assertTrue(inspect_markers(render(0,'misaligned-product','process',timestamp=1234))[1])
        self.assertFalse(inspect_markers(render(0,'normal','process',timestamp=1234))[1])
        self.assertFalse(np.array_equal(render(50,'normal','entry'),render(50,'normal','exit')))
        self.assertEqual(sensor_index(100+4.4)-sensor_index(100),1)

    def test_visual_alert_classification_and_jam_correlation(self):
        expected={'ProductStalled':'PRODUCT_STALLED','ProductWrongDirection':'WRONG_DIRECTION',
                  'ProductionCountMismatch':'COUNT_MISMATCH','VisualQualityFailure':'VISUAL_QUALITY_FAILURE',
                  'VisionPersonInRestrictedZone':'RESTRICTED_ZONE_VIOLATION'}
        for name,kind in expected.items():
            self.assertEqual(classify(name,{},{}),(kind,{'ProductStalled':'process-tracking','ProductionCountMismatch':'product-count'}.get(name,kind)))
        self.assertTrue(jam_compatible('ProductStalled',{}))
        self.assertTrue(jam_compatible('ProductExcessiveDwell',{}))
        self.assertFalse(jam_compatible('VisualQualityFailure',{}))


class HubTests(unittest.TestCase):
    def setUp(self):
        self.registry=CollectorRegistry()
        self.publish=Mock()
        self.hub=Hub(self.publish,registry=self.registry)

    def test_latest_frame_queues_are_bounded_per_camera(self):
        inference=SharedInference(self.hub)
        self.hub.settings=type(self.hub.settings)(every=1)
        frame=np.zeros((360,640,3),np.uint8)
        for stamp in range(4):
            for camera in CAMERAS:
                inference.submit(camera,frame,stamp)
        self.assertEqual(len(inference.pending),3)
        self.assertTrue(all(v[1]==3 for v in inference.pending.values()))
        self.assertEqual(self.registry.get_sample_value('vision_dropped_frames_total',{'camera':'entry'}),3)
        inference.invalidate('entry')
        self.assertNotIn('entry',inference.pending)

    def test_one_model_services_three_independent_camera_trackers(self):
        self.hub.settings=type(self.hub.settings)(every=1)
        model=Mock(names={39:'bottle'})
        model.predict.return_value=[]
        loader=Mock(return_value=model)
        inference=SharedInference(self.hub,loader=loader)
        try:
            inference.start()
            for camera in CAMERAS:
                inference.submit(camera,np.zeros((360,640,3),np.uint8),time.time())
            deadline=time.monotonic()+3
            while model.predict.call_count<3 and time.monotonic()<deadline:
                threading.Event().wait(.01)
            self.assertEqual(model.predict.call_count,3)
            loader.assert_called_once()
            self.assertTrue(all(c['tracking_ready'] for c in self.hub.cameras.values()))
        finally:
            self.hub.stop.set()
            inference.close()

    def test_invalid_optional_yolo_keeps_raw_and_classical_cv(self):
        with patch.dict('os.environ',{'YOLO_CONFIDENCE':'invalid'}):
            with self.assertLogs('services.cv_detector.multicamera',level='ERROR'):
                hub=Hub(Mock(),registry=CollectorRegistry())
        inference=SharedInference(hub,loader=Mock())
        inference.start()
        self.assertIsNone(inference.thread)
        hub.frame('process',render(10,'normal'),time.time())
        self.assertTrue(hub.cameras['process']['up'])
        self.assertFalse(hub.ready)

    def test_inflight_result_rejected_after_camera_loss(self):
        entered,release=threading.Event(),threading.Event()
        model=Mock(names={39:'bottle'})
        def predict(*args,**kwargs):
            entered.set()
            release.wait(2)
            return []
        model.predict.side_effect=predict
        self.hub.settings=type(self.hub.settings)(every=1)
        inference=SharedInference(self.hub,loader=lambda _:model)
        try:
            inference.start()
            inference.submit('entry',np.zeros((360,640,3),np.uint8),time.time())
            self.assertTrue(entered.wait(2))
            inference.invalidate('entry')
            release.set()
        finally:
            self.hub.stop.set()
            inference.close()
        self.assertFalse(self.hub.cameras['entry']['tracking_ready'])

    def test_reconciliation_suspended_during_planned_stop(self):
        from services.opcua_sim.process import sample
        now=time.time()
        for c in self.hub.cameras.values():
            c.update(up=True,tracking_ready=True,updated=now,processed=now)
        self.hub.plc=dict(timestamp=now,values=sample(0,'normal',100))
        self.hub.maintain()
        self.assertTrue(self.hub.reconciled['ready'])
        self.hub.plc['values']=sample(0,'stopped',100)
        self.hub.maintain()
        self.assertFalse(self.hub.reconciled['ready'])
        self.assertIsNone(self.hub.reconciled['difference'])

    def test_quality_checks_work_without_yolo_inference(self):
        self.hub.enabled=False
        self.hub.frame('process',render(10,'misaligned-product'),time.time())
        self.hub.maintain()
        self.assertTrue(self.hub.cameras['process']['quality'])
        self.assertIn('visual_quality_failure',self.hub.cameras['process']['anomalies'])
        self.assertEqual(self.registry.get_sample_value('vision_quality_failure',{'camera':'process'}),1)

    def test_counters_and_ids_not_prometheus_labels(self):
        now=time.time()
        frame=render(10,'normal')
        self.hub.inferred('entry',frame,[detection(290)],now-.5,.04)
        self.hub.inferred('entry',frame,[detection(330)],now,.04)
        self.assertEqual(self.registry.get_sample_value('vision_products_entered_total'),1)
        for metric in self.registry.collect():
            for sample in metric.samples:
                self.assertNotIn('track_id',sample.labels)
        events=[c.args[1] for c in self.publish.call_args_list]
        self.assertTrue(any(e.get('event')=='product_crossed' for e in events))

    def test_control_room_twin_and_stale_video(self):
        client=TestClient(create_app(self.hub))
        self.assertIn('Industrial Vision Control Room',client.get('/').text)
        self.assertEqual(client.get('/cameras/invalid/snapshot.jpg').status_code,404)
        self.assertEqual(client.get('/snapshot.jpg').status_code,503)
        self.hub.frame('process',render(10,'normal'),time.time())
        self.assertEqual(client.get('/snapshot.jpg').status_code,200)
        self.assertEqual(client.get('/cameras/process/heatmap.jpg').status_code,200)
        twin=client.get('/api/twin').json()
        self.assertEqual(len(twin['nodes']),5)
        self.assertEqual(next(n for n in twin['nodes'] if n['id']=='entry')['state'],'unavailable')
        self.hub.cameras['process']['updated']-=10
        self.hub.maintain()
        self.assertEqual(client.get('/snapshot.jpg').status_code,503)
        self.assertEqual(client.post('/api/reconciliation/reset').status_code,200)
        self.assertIn("script-src 'self'",client.get('/').headers['content-security-policy'])


if __name__=='__main__':
    unittest.main()
