"""Shared physical cadence, not detector output. One nominal product every 4.4 s."""
import math

PIXELS_PER_SECOND = 50.0
PRODUCT_SPACING = 220
CAMERAS = ('entry', 'process', 'exit')
OFFSETS = dict(entry=0, process=560, exit=1120)
COUNTING_X = 320


def sensor_index(timestamp):
    # Bottle centre is approximately x+20; scene sprites start 100 px before view.
    return math.floor((timestamp * PIXELS_PER_SECOND - 400) / PRODUCT_SPACING)
