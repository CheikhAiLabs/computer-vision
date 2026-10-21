"""Local conveyor compositor. Assets and their licenses are listed in SOURCES.md."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

WIDTH, HEIGHT, FPS = 640, 360, 10
SCENARIOS = {"normal", "jam", "dirty-camera", "dark-camera", "blur-camera",
             "object-mix", "person-zone", "fallen-object", "crowded-line"}
ASSETS = Path(__file__).resolve().parents[2] / "assets" / "objects"


@lru_cache(maxsize=24)
def sprite(name, height, rotated=False):
    source = cv2.imread(str(ASSETS / (name + ".png")), cv2.IMREAD_UNCHANGED)
    if source is None:
        raise FileNotFoundError(ASSETS / (name + ".png"))
    image = cv2.resize(source, (round(source.shape[1] * height / source.shape[0]), height),
                       interpolation=cv2.INTER_AREA)
    return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE) if rotated else image


def composite(image, asset, x, y):
    h, w = asset.shape[:2]
    x1, y1, x2, y2 = max(0, x), max(0, y), min(WIDTH, x+w), min(HEIGHT, y+h)
    if x2 <= x1 or y2 <= y1:
        return
    crop = asset[y1-y:y2-y, x1-x:x2-x]
    alpha = crop[:, :, 3:4].astype(np.float32) / 255
    image[y1:y2, x1:x2] = crop[:, :, :3] * alpha + image[y1:y2, x1:x2] * (1-alpha)


def parcel(image, x, y, size, index):
    color = [(111, 159, 192), (160, 145, 112), (119, 158, 140)][index % 3]
    cv2.rectangle(image, (x+3,y+5), (x+size+7,y+size+5), (34,38,40), -1)
    cv2.rectangle(image, (x,y), (x+size,y+size), color, -1)
    cv2.rectangle(image, (x,y), (x+size,y+size), (75,95,110), 1)
    cv2.line(image, (x+size//2,y), (x+size//2,y+size), (190,202,207), 5)
    cv2.rectangle(image, (x+5,y+size//2), (x+size//2-5,y+size-7), (225,229,227), -1)
    for offset in range(0, max(1,size//2-12), 3):
        cv2.line(image,(x+7+offset,y+size//2+4),(x+7+offset,y+size-10),(70,76,76),1)


def render(frame_number: int, scenario: str):
    image = np.full((HEIGHT, WIDTH, 3), (90, 98, 104), dtype=np.uint8)
    # Steel wall panels and service walkway.
    for x in range(0, WIDTH, 80):
        cv2.line(image, (x,48), (x,110), (108,115,120), 1)
        cv2.circle(image, (x+8,58), 2, (164,171,174), -1)
    cv2.rectangle(image, (0,285), (WIDTH,310), (63,70,75), -1)
    for x in range(-20, WIDTH, 28):
        cv2.line(image,(x,286),(x+18,309),(114,157,177),6)
    cv2.rectangle(image, (0,108), (WIDTH,282), (170,178,182), -1)
    cv2.rectangle(image, (0,126), (WIDTH,265), (55,62,65), -1)
    speed = 1 if scenario == "jam" else 5
    for x in range(-40, WIDTH+40, 32):
        pos = (x+frame_number*speed) % (WIDTH+40)-20
        cv2.line(image,(pos,130),(pos-20,260),(78,86,89),2)
    for y in (116,274):
        cv2.line(image,(0,y),(WIDTH,y),(212,217,219),2)
        for x in range(12,WIDTH,48):
            cv2.circle(image,(x,y),3,(75,83,88),-1)
    count, spacing = (10,76) if scenario == "crowded-line" else (5,150)
    for index in range(count):
        x = (index*spacing+frame_number*speed) % (count*spacing)-60
        if scenario in {"object-mix", "crowded-line"} and index % 3 == 1:
            parcel(image,x,184,52+(index%2)*12,index)
        elif scenario in {"object-mix", "crowded-line"} and index == 2:
            composite(image,sprite('cup',120),x,245-120)
        else:
            height = 108 + (index % 3)*12
            cv2.ellipse(image,(x+18,247),(26,6),0,0,360,(35,40,42),-1)
            composite(image,sprite('bottle',height),x,245-height)
    if scenario == "fallen-object":
        composite(image,sprite('bottle',108,True),255,285)
    if scenario == "person-zone":
        composite(image,sprite('person',235),395,64)
    if scenario == "jam":
        # Preserve the original deterministic obstruction area and color.
        cv2.rectangle(image,(260,135),(380,260),(15,15,240),-1)
        cv2.putText(image,"JAM",(275,210),cv2.FONT_HERSHEY_SIMPLEX,0.8,(255,255,255),2)
    cv2.rectangle(image,(0,0),(WIDTH,47),(31,42,49),-1)
    cv2.putText(image,"LINE 01 / VISION INSPECTION",(18,29),cv2.FONT_HERSHEY_SIMPLEX,
                0.65,(225,233,236),1,cv2.LINE_AA)
    cv2.circle(image,(607,24),5,(130,200,125),-1)
    cv2.rectangle(image,(0,315),(WIDTH,HEIGHT),(31,42,49),-1)
    cv2.putText(image,f"{scenario.upper()}  |  FRAME {frame_number:08d}  |  LOCAL SIMULATION",
                (14,340),cv2.FONT_HERSHEY_SIMPLEX,0.43,(220,228,230),1,cv2.LINE_AA)
    if scenario == "dirty-camera":
        cv2.rectangle(image,(150,75),(490,285),(5,5,5),-1)
    elif scenario == "dark-camera":
        image = (image.astype(np.float32)*0.07).astype(np.uint8)
    elif scenario == "blur-camera":
        image = cv2.GaussianBlur(image,(51,51),16)
    return image
