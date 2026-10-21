"""Optional maintainer tool: prepare licensed source images downloaded per SOURCES.md.
No network access. Normal builds and camera rendering use the committed PNGs.
"""
import argparse
from pathlib import Path
import cv2
import numpy as np


def read(path):
    image = cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f'Cannot decode source image: {path}')
    return image


def blue_suit(image, selection):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    sel=(hsv[:,:,0]<30)&(hsv[:,:,1]>110)&selection
    hsv[:,:,0][sel]=105
    return cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bottle',type=Path,required=True)
    parser.add_argument('--person',type=Path,required=True)
    parser.add_argument('--cup',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'assets/objects')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    bottle=read(args.bottle)
    cv2.imwrite(str(args.output/'bottle.png'),cv2.resize(bottle,(100,320),interpolation=cv2.INTER_AREA))
    person=read(args.person)
    mask=np.zeros(person.shape[:2],np.uint8)
    points=[(22,511),(18,403),(29,311),(47,264),(99,219),(119,200),(129,163),(153,150),
            (178,149),(173,125),(156,110),(152,70),(166,44),(199,23),(240,16),(279,26),
            (298,59),(303,87),(291,117),(280,142),(272,164),(304,214),(326,236),(347,269),
            (361,343),(406,344),(448,362),(479,399),(497,444),(511,493),(511,511)]
    cv2.fillPoly(mask,[np.array(points)],255)
    mask=cv2.GaussianBlur(mask,(3,3),0)
    person=blue_suit(person,np.indices(mask.shape)[0]>220)
    cv2.imwrite(str(args.output/'person.png'),cv2.resize(np.dstack([person,mask]),(256,256),interpolation=cv2.INTER_AREA))
    cup=read(args.cup)
    mask=np.zeros(cup.shape[:2],np.uint8)
    points=[(173,108),(180,77),(198,50),(230,29),(269,16),(311,15),(348,23),(381,44),
            (402,75),(412,109),(406,144),(395,178),(382,209),(365,240),(340,267),
            (308,285),(269,290),(246,302),(225,311),(201,303),(195,285),(207,254),
            (220,234),(207,211),(194,189),(182,157)]
    cv2.fillPoly(mask,[np.array(points)],255)
    mask=cv2.GaussianBlur(mask,(3,3),0)
    cutout=np.dstack([cup,mask])[12:315,170:415]
    cv2.imwrite(str(args.output/'cup.png'),cv2.resize(cutout,(98,121),interpolation=cv2.INTER_AREA))


if __name__=='__main__':
    main()
