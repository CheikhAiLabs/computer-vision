"""Backward-compatible process stream plus shared multi-camera CV runtime."""
import logging
import os
import threading
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS','rtsp_transport;tcp')
import cv2
from prometheus_client import start_http_server
import uvicorn
from common.config import RTSP_URL
from common.mqtt import start_client,publish,close
from common.runtime import STOP,setup


def open_capture(url=RTSP_URL):
    return cv2.VideoCapture(url,cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,4000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,4000])


def main():
    from services.cv_detector.multicamera import Hub,SharedInference,capture_camera,context_loop
    from services.cv_detector.control_room import create_app
    from common.line import CAMERAS
    cv2.setNumThreads(1)
    client=None
    hub=Hub(lambda topic,payload:publish(client,topic,payload))
    client=start_client('cv-detector',hub.receive,'factory/line1/#')
    inference=SharedInference(hub)
    start_http_server(9104)
    inference.start()
    threads=[threading.Thread(target=capture_camera,args=(hub,inference,c),name='capture-'+c,daemon=True) for c in CAMERAS]
    threads.append(threading.Thread(target=context_loop,args=(hub,),name='vision-context',daemon=True))
    server=uvicorn.Server(uvicorn.Config(create_app(hub),host='0.0.0.0',port=8083,log_level='warning'))
    threads.append(threading.Thread(target=server.run,name='control-room',daemon=True))
    for thread in threads:
        thread.start()
    try:
        while not STOP.wait(1):
            hub.maintain()
    finally:
        hub.stop.set()
        server.should_exit=True
        inference.close()
        for thread in threads:
            thread.join(timeout=5)
        close(client)


if __name__=='__main__':
    setup()
    main()
