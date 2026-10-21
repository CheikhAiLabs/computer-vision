import unittest
import numpy as np
from services.camera_sim.scene import render
from services.cv_detector.vision import analyze
from services.ml_anomaly.model import train, infer
from services.opcua_sim.process import sample


class VisionTests(unittest.TestCase):
    def test_normal_animation_has_no_anomaly(self):
        for frame in range(0,150,7):
            values, reasons = analyze(render(frame,"normal"))
            self.assertEqual(reasons, [], (frame,values))

    def test_visual_scenarios(self):
        for scenario, reason in [('jam','red-object'),('dirty-camera','dirty-camera'),
                                 ('dark-camera','dark-camera'),('blur-camera','blur-camera')]:
            with self.subTest(scenario=scenario):
                _, reasons = analyze(render(40,scenario))
                self.assertIn(reason,reasons)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = train()

    def test_normal_process_does_not_trigger(self):
        for tick in range(0,3000,19):
            score, anomaly = infer(self.model,sample(tick,'normal',10))
            self.assertFalse(anomaly,score)

    def test_multivariate_jam_triggers(self):
        score, anomaly = infer(self.model,sample(0,'jam',10))
        self.assertTrue(anomaly,score)

    def test_major_single_sensor_faults_usually_trigger(self):
        for scenario in ("overheat", "vibration"):
            predictions = [infer(self.model,sample(tick,scenario,10))[1]
                           for tick in range(0,3000,19)]
            self.assertGreaterEqual(sum(predictions) / len(predictions), 0.9, scenario)

    def test_nonfinite_input_rejected(self):
        values = sample(0,'normal',0)
        values['Vibration'] = np.nan
        with self.assertRaises(ValueError):
            infer(self.model,values)


if __name__ == '__main__':
    unittest.main()
