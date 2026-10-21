import numpy as np
from sklearn.ensemble import IsolationForest
from common.config import FEATURES


def train():
    rng = np.random.default_rng(42)
    normal = np.column_stack([rng.normal(1.2, 0.06, 4000), rng.normal(45, 3, 4000),
                              rng.normal(0.12, 0.025, 4000), rng.normal(0.985, 0.008, 4000),
                              np.zeros(4000)])
    # Sensitive demo boundary: the broad training tails are wider than the PLC
    # operating envelope. This trades false positives for single-sensor sensitivity.
    return IsolationForest(n_estimators=160, contamination=0.12,
                           random_state=42, n_jobs=1).fit(normal)


def infer(model, values):
    vector = np.array([[float(values[name]) for name in FEATURES]])
    if not np.isfinite(vector).all():
        raise ValueError("Non-finite telemetry features")
    # Negative decision_function means outside the learned normal boundary.
    score = -float(model.decision_function(vector)[0])
    return score, score > 0
