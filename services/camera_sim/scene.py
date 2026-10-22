"""Local conveyor compositor. Assets and their licenses are listed in SOURCES.md."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from common.line import OFFSETS, PIXELS_PER_SECOND, PRODUCT_SPACING

WIDTH, HEIGHT, FPS = 640, 360, 10
SCENARIOS = {"normal", "jam", "dirty-camera", "dark-camera", "blur-camera",
             "object-mix", "person-zone", "fallen-object", "crowded-line",
             "misaligned-product", "stalled-product", "wrong-direction", "count-mismatch"}
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


def can(image,x,y):
    """Small steel can with an inspection fiducial, no semantic detection metadata."""
    cv2.ellipse(image,(x+19,y+69),(23,5),0,0,360,(32,39,43),-1)
    cv2.rectangle(image,(x,y+5),(x+38,y+65),(148,157,162),-1)
    for offset in range(2,35):
        shade=round(120+75*np.sin(offset/38*np.pi))
        cv2.line(image,(x+offset,y+6),(x+offset,y+64),(shade,shade+2,shade+3),1)
    cv2.rectangle(image,(x+2,y+22),(x+36,y+48),(116,132,85),-1)
    cv2.ellipse(image,(x+19,y+5),(19,5),0,0,360,(194,203,208),-1)
    cv2.ellipse(image,(x+19,y+5),(15,3),0,0,360,(116,128,137),1)
    cv2.ellipse(image,(x+19,y+65),(19,4),0,0,180,(199,207,211),2)
    cv2.rectangle(image,(x+7,y+28),(x+31,y+38),(220,210,20),-1)


def render(frame_number: int, scenario: str, camera='process', timestamp=None, scenario_started=None):
    """Three windows on one conveyor; timestamp controls motion, never detections."""
    moment = frame_number/FPS if timestamp is None else timestamp
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
    position = moment * PIXELS_PER_SECOND
    if scenario == 'jam' or (scenario == 'stalled-product' and camera == 'process'):
        position = (scenario_started or 0) * PIXELS_PER_SECOND
    if scenario == 'wrong-direction' and camera == 'process':
        position = -position
    for x in range(-40, WIDTH+40, 32):
        pos = round((x+position) % (WIDTH+40)-20)
        cv2.line(image,(pos,130),(pos-20,260),(78,86,89),2)
    for y in (116,274):
        cv2.line(image,(0,y),(WIDTH,y),(212,217,219),2)
        for x in range(12,WIDTH,48):
            cv2.circle(image,(x,y),3,(75,83,88),-1)
    count, spacing = (24,90) if scenario == "crowded-line" else (10,PRODUCT_SPACING)
    for index in range(count):
        x = round((index*spacing+position-OFFSETS[camera]) % (count*spacing)-100)
        if scenario == 'count-mismatch' and camera == 'exit' and index % 2 == 0:
            continue
        if scenario in {"object-mix", "crowded-line"} and index % 3 == 1:
            parcel(image,x,184,52+(index%2)*12,index)
            # A deliberate cyan inspection marker, segmented by OpenCV, not YOLO.
            cv2.rectangle(image,(x+12,191),(x+36,201),(220,210,20),-1)
        elif scenario in {"object-mix", "crowded-line"} and index == 2:
            composite(image,sprite('cup',120),x,245-120)
        elif scenario in {"object-mix", "crowded-line"} and index % 5 == 3:
            can(image,x,177)
        else:
            height = 108 + (index % 3)*12
            cv2.ellipse(image,(x+18,247),(26,6),0,0,360,(35,40,42),-1)
            y = 245-height
            rotated = scenario == 'misaligned-product' and camera == 'process'
            if rotated:
                composite(image,sprite('bottle',height,True),x,193)
                cv2.rectangle(image,(x+4,205),(x+90,211),(220,210,20),-1)
            else:
                composite(image,sprite('bottle',height),x,y)
    if scenario == "fallen-object" and camera == 'process':
        composite(image,sprite('bottle',108,True),255,285)
        cv2.rectangle(image,(262,297),(326,303),(220,210,20),-1)
    if scenario == "person-zone" and camera == 'process':
        composite(image,sprite('person',235),395,64)
    if scenario == "jam" and camera == 'process':
        # Preserve the original deterministic obstruction area and color.
        cv2.rectangle(image,(260,135),(380,260),(15,15,240),-1)
        cv2.putText(image,"JAM",(275,210),cv2.FONT_HERSHEY_SIMPLEX,0.8,(255,255,255),2)
    cv2.rectangle(image,(0,0),(WIDTH,47),(31,42,49),-1)
    cv2.putText(image,f"LINE 01 / {camera.upper()} CAM",(18,29),cv2.FONT_HERSHEY_SIMPLEX,
                0.65,(225,233,236),1,cv2.LINE_AA)
    # Station hardware, sensor heads, inspection portal and steel product trays.
    for sx in (70,552):
        cv2.rectangle(image,(sx,65),(sx+12,107),(58,68,77),-1)
        cv2.rectangle(image,(sx+3,76),(sx+9,89),(210,190,65),-1)
    if camera == 'process':
        cv2.rectangle(image,(215,65),(422,102),(52,65,74),-1)
        cv2.rectangle(image,(220,69),(417,98),(83,99,110),1)
        cv2.putText(image,'OPTICAL INSPECTION / CELL 02',(229,86),cv2.FONT_HERSHEY_SIMPLEX,.32,(198,215,223),1)
    else:
        for tx in (250,360):
            cv2.rectangle(image,(tx,70),(tx+62,96),(75,88,98),-1)
            for stripe in range(4):
                cv2.line(image,(tx+5,75+stripe*5),(tx+55,75+stripe*5),(107,120,129),1)
    cv2.putText(image,{'entry':'INFEED / PHOTOEYE 01','process':'INSPECTION / GUARDED CELL',
                       'exit':'OUTFEED / PHOTOEYE 02'}[camera],(15,302),cv2.FONT_HERSHEY_SIMPLEX,.4,(222,229,231),1)
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
