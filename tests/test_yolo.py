"""Offline unit tests. Model inference is mocked; no weights or Ultralytics needed."""
from dataclasses import replace
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch
import numpy as np
from prometheus_client import CollectorRegistry
from services.cv_detector.yolo import (Settings, Worker, Metrics, parse_results, overlaps,
                                       messages, load_model, DETECTIONS_TOPIC, SAFETY_TOPIC)
from services.cv_detector.annotated import Preview
from services.camera_sim.scene import render, SCENARIOS
from services.cv_detector.vision import analyze


class Tensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


def result(boxes=None, scores=None, classes=None):
    return SimpleNamespace(names={0:'person',39:'bottle',7:'truck'}, boxes=SimpleNamespace(
        xyxy=Tensor(boxes or [[390,70,620,300]]),
        conf=Tensor(scores or [.96]), cls=Tensor(classes or [0])))


def eventually(check):
    end = time.monotonic()+3
    while time.monotonic() < end:
        if check():
            return
        threading.Event().wait(.01)
    raise AssertionError('Worker did not reach expected state')


class ParsingTests(unittest.TestCase):
    def test_parse_and_clip_boxes(self):
        parsed = parse_results([result([[-2.6,2.2,700,370]])],640,360,.45)
        self.assertEqual(parsed,[{'class':'person','confidence':.96,'bbox':[0,2,640,360]}])

    def test_invalid_boxes_scores_and_classes_are_dropped(self):
        inputs = [([1,2,1,3],.9,0), ([1,2,float('nan'),3],.9,0),
                  ([1,2,3,4],float('inf'),0),([1,2,3,4],.4,0),
                  ([1,2,3,4],1.1,0),([1,2,3,4],.9,7),
                  ([1,2,3,4],.9,999),([1,2,3,4],.9,.5),([1,2,3],.9,0)]
        for box,score,cls in inputs:
            with self.subTest(box=box,score=score,cls=cls):
                self.assertEqual(parse_results([result([box],[score],[cls])],640,360,.45),[])
        self.assertEqual(parse_results([SimpleNamespace(boxes=None)],640,360,.45),[])

    def test_zone_positive_area_intersection(self):
        zone = (.5,.5,.8,.8)
        for box,expected in [([40,40,60,60],True),([50,50,80,80],True),
                             ([0,0,49,49],False),([0,0,50,50],False),
                             ([0,0,100,100],True),([80,50,90,60],False)]:
            self.assertEqual(overlaps(box,zone,100,100),expected,box)

    def test_detection_and_safety_payloads(self):
        detections = parse_results([result()],640,360,.45)
        payload,safety = messages(detections,Settings(),640,360,100,99)
        self.assertEqual(payload['model'],'yolo26n.pt')
        self.assertEqual(payload['site'],'local')
        self.assertEqual(payload['line'],'line1')
        self.assertEqual(payload['detections'],detections)
        self.assertTrue(payload['timestamp'].endswith('+00:00'))
        self.assertEqual(payload['source_timestamp'],99)
        self.assertEqual(safety[0]['event'],'person_in_restricted_zone')
        self.assertEqual(safety[0]['bbox'],[390,70,620,300])
        for d in [{'class':'bottle','confidence':.9,'bbox':[390,70,620,300]},
                  {'class':'person','confidence':.9,'bbox':[0,0,10,10]}]:
            self.assertEqual(messages([d],Settings(),640,360,100,99)[1],[])

    def test_invalid_config(self):
        for values in [dict(every=0),dict(confidence=float('nan')),dict(ttl=-1),
                       dict(threads=0),dict(zone=(.8,.1,.2,.5)),dict(zone=(0,0,1))]:
            with self.assertRaises(ValueError):
                Settings(**values)

    def test_missing_weights_never_import_ultralytics(self):
        with patch.dict('sys.modules',{'ultralytics':None,'torch':None}):
            with self.assertRaises(FileNotFoundError):
                load_model(Settings(model='/definitely-missing/local.pt'))


class WorkerTests(unittest.TestCase):
    def worker(self, **kwargs):
        registry = CollectorRegistry()
        publish = Mock()
        worker = Worker(publish,settings=Settings(every=1),registry=registry,**kwargs)
        self.addCleanup(worker.close)
        return worker,registry,publish

    def test_disabled_never_initializes_or_predicts(self):
        loader = Mock(side_effect=AssertionError('must not be called'))
        worker,registry,publish = self.worker(enabled=False,loader=loader)
        worker.start()
        worker.submit(np.zeros((360,640,3),np.uint8),time.time())
        self.assertIsNone(worker.thread)
        loader.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(registry.get_sample_value('yolo_enabled'),0)
        self.assertEqual(registry.get_sample_value('yolo_model_ready'),0)

    def test_initialization_failure_is_contained(self):
        failed = threading.Event()
        def loader(settings):
            failed.set()
            raise RuntimeError('bad model')
        worker,registry,publish = self.worker(enabled=True,loader=loader)
        with self.assertLogs('services.cv_detector.yolo',level='ERROR'):
            worker.start()
            self.assertTrue(failed.wait(2))
            eventually(lambda:registry.get_sample_value('yolo_model_ready')==0)
            worker.close()
        self.assertEqual(registry.get_sample_value('yolo_enabled'),1)
        publish.assert_not_called()

    def test_parsed_result_updates_metrics_and_publishes(self):
        model=Mock(names={0:'person',39:'bottle'})
        model.predict.return_value=[result()]
        worker,registry,publish = self.worker(enabled=True,loader=lambda _:model)
        worker.start()
        worker.submit(np.zeros((360,640,3),np.uint8),time.time())
        eventually(lambda:publish.call_count==2)
        self.assertEqual([c.args[0] for c in publish.call_args_list],[DETECTIONS_TOPIC,SAFETY_TOPIC])
        self.assertEqual(registry.get_sample_value('yolo_model_ready'),1)
        self.assertEqual(registry.get_sample_value('yolo_objects_detected'),1)
        self.assertEqual(registry.get_sample_value('yolo_detections_total'),1)
        self.assertEqual(registry.get_sample_value('yolo_class_detections',{'class':'person'}),1)
        self.assertEqual(registry.get_sample_value('yolo_restricted_zone_violation'),1)
        self.assertGreater(registry.get_sample_value('yolo_last_inference_timestamp_seconds'),0)
        self.assertEqual(registry.get_sample_value('yolo_inference_duration_seconds_count'),1)
        self.assertIsNotNone(worker.snapshot())
        worker.invalidate()
        self.assertIsNone(worker.snapshot())
        self.assertEqual(registry.get_sample_value('yolo_restricted_zone_violation'),0)

    def test_inference_exception_is_contained(self):
        model = Mock(names={0:'person'})
        model.predict.side_effect=RuntimeError('inference failed')
        worker,registry,publish=self.worker(enabled=True,loader=lambda _:model)
        with self.assertLogs('services.cv_detector.yolo',level='ERROR'):
            worker.start()
            worker.submit(np.zeros((20,20,3),np.uint8),time.time())
            eventually(lambda:model.predict.called and registry.get_sample_value('yolo_model_ready')==0)
            worker.close()
        publish.assert_not_called()
        self.assertIsNone(worker.snapshot())

    def test_stream_loss_discards_inflight_result(self):
        entered,release = threading.Event(),threading.Event()
        model=Mock(names={0:'person'})
        def predict(*args,**kwargs):
            entered.set()
            release.wait(2)
            return [result()]
        model.predict.side_effect=predict
        worker,registry,publish=self.worker(enabled=True,loader=lambda _:model)
        worker.start()
        worker.submit(np.zeros((360,640,3),np.uint8),time.time())
        self.assertTrue(entered.wait(2))
        worker.invalidate()
        release.set()
        worker.close()
        publish.assert_not_called()
        self.assertEqual(registry.get_sample_value('yolo_restricted_zone_violation'),0)

    def test_stale_results_expire_and_empty_result_clears_metrics(self):
        worker,registry,_=self.worker(enabled=False)
        worker.latest={'source_timestamp':time.time()-10,'detections':[]}
        worker.metrics.violation.set(1)
        self.assertIsNone(worker.snapshot())
        self.assertEqual(registry.get_sample_value('yolo_restricted_zone_violation'),0)
        worker.metrics.record([{'class':'person'}],[{}],10,.1)
        worker.metrics.record([],[],11,.1)
        self.assertEqual(registry.get_sample_value('yolo_objects_detected'),0)
        self.assertEqual(registry.get_sample_value('yolo_class_detections',{'class':'person'}),0)
        self.assertEqual(registry.get_sample_value('yolo_detections_total'),1)

    def test_sampling_and_queue_are_bounded(self):
        worker,_,_=self.worker(enabled=True)
        worker.settings=replace(worker.settings,every=5)
        frame=np.zeros((20,20,3),np.uint8)
        for _ in range(4):
            worker.submit(frame,1)
        self.assertIsNone(worker.pending)
        worker.submit(frame,2)
        self.assertEqual(worker.pending[1],2)
        for _ in range(5):
            worker.submit(frame,3)
        self.assertEqual(worker.pending[1],3)


class PreviewAndSceneTests(unittest.TestCase):
    def test_preview_decodes_and_expires(self):
        import cv2
        from fastapi.testclient import TestClient
        worker=Worker(Mock(),enabled=False,registry=CollectorRegistry())
        preview=Preview()
        client=TestClient(preview.app())
        self.assertEqual(client.get('/healthz').status_code,200)
        self.assertEqual(client.get('/snapshot.jpg').status_code,503)
        preview.update(render(40,'normal'),[],worker)
        response=client.get('/snapshot.jpg')
        self.assertEqual(response.status_code,200)
        self.assertEqual(cv2.imdecode(np.frombuffer(response.content,np.uint8),cv2.IMREAD_COLOR).shape,(360,640,3))
        preview.updated-=10
        self.assertEqual(client.get('/snapshot.jpg').status_code,503)

    def test_all_visual_scenarios_and_normal_recovery(self):
        for scenario in SCENARIOS:
            for tick in (0,7,40,100,149):
                image=render(tick,scenario)
                self.assertEqual(image.shape,(360,640,3))
                _,reasons=analyze(image)
                if scenario in {'normal','object-mix','person-zone','fallen-object','crowded-line'}:
                    self.assertEqual(reasons,[],(tick,scenario,reasons))
                self.assertEqual(analyze(render(tick,'normal'))[1],[])


if __name__ == '__main__':
    unittest.main()
