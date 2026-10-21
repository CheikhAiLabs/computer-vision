"""CPU-friendly heuristics calibrated against the synthetic scene, not real plants."""
import cv2
import numpy as np


def analyze(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, (0, 120, 80), (10, 255, 255)) | cv2.inRange(hsv, (170, 120, 80), (180, 255, 255))
    height, width = gray.shape
    mask = np.zeros(gray.shape, dtype=bool)
    mask[height // 3:2 * height // 3, width // 3:2 * width // 3] = True
    values = {"red_pixel_ratio": float(np.count_nonzero(red) / gray.size),
              "frame_brightness": float(gray.mean()),
              "laplacian_variance": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
              "center_to_border_brightness_ratio": float(gray[mask].mean() / max(gray[~mask].mean(), 1))}
    reasons = []
    if values["red_pixel_ratio"] > 0.025:
        reasons.append("red-object")
    if values["frame_brightness"] < 25:
        reasons.append("dark-camera")
    else:
        if values["center_to_border_brightness_ratio"] < 0.25:
            reasons.append("dirty-camera")
        if values["laplacian_variance"] < 30:
            reasons.append("blur-camera")
    return values, reasons
