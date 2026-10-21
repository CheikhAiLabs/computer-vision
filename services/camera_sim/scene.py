import cv2
import numpy as np

WIDTH, HEIGHT, FPS = 640, 360, 10
SCENARIOS = {"normal", "jam", "dirty-camera", "dark-camera", "blur-camera"}


def render(frame_number: int, scenario: str):
    image = np.full((HEIGHT, WIDTH, 3), (115, 110, 100), dtype=np.uint8)
    cv2.rectangle(image, (0, 100), (WIDTH, 290), (170, 170, 170), -1)
    cv2.rectangle(image, (0, 125), (WIDTH, 265), (65, 70, 70), -1)
    for x in range(-40, WIDTH + 40, 40):
        pos = (x + frame_number * 5) % (WIDTH + 40) - 20
        cv2.line(image, (pos, 130), (pos - 20, 260), (90, 95, 95), 2)
    for index in range(5):
        x = (index * 150 + frame_number * 5) % 750 - 60
        cv2.rectangle(image, (x, 165), (x + 45, 230), (70, 200, 80), -1)
        cv2.rectangle(image, (x + 8, 150), (x + 37, 165), (200, 220, 200), -1)
        cv2.line(image, (x + 8, 180), (x + 37, 180), (245, 245, 245), 3)
    if scenario == "jam":
        cv2.rectangle(image, (260, 135), (380, 260), (15, 15, 240), -1)
        cv2.putText(image, "JAM", (275, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(image, "LINE 1 | INDUSTRIAL VISION", (18, 38), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (240, 240, 240), 2)
    cv2.putText(image, f"FRAME {frame_number:08d}  {scenario.upper()}", (18, 330),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
    if scenario == "dirty-camera":
        cv2.rectangle(image, (150, 75), (490, 285), (5, 5, 5), -1)
    elif scenario == "dark-camera":
        image = (image.astype(np.float32) * 0.07).astype(np.uint8)
    elif scenario == "blur-camera":
        image = cv2.GaussianBlur(image, (51, 51), 16)
    return image
