"""Observe all four real vision MQTT channels while running vision-test."""
import argparse
import json
import threading
import uuid
from common.mqtt import start_client,close


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    required={f'factory/line1/vision/{suffix}' for suffix in ('events','counts','safety','quality')}
    seen={}
    done=threading.Event()
    errors=[]
    def receive(client,userdata,message):
        if message.topic not in required:
            return
        try:
            payload=json.loads(message.payload)
            assert payload['line']=='line1' and payload['site']=='local'
            assert isinstance(payload['timestamp'],(int,float))
            if not message.topic.endswith('/counts'):
                assert payload['camera'] in ('entry','process','exit')
                assert payload.get('event')
            seen[message.topic]=payload
            if required<=seen.keys():
                done.set()
        except (ValueError,AssertionError,KeyError) as exc:
            errors.append(str(exc))
            done.set()
    client=start_client('vision-check-'+uuid.uuid4().hex[:8],receive,'factory/line1/vision/#')
    try:
        assert done.wait(args.timeout),f'Missing real topics: {required-seen.keys()}'
        assert not errors,errors
        print(json.dumps(seen,indent=2))
        print('PASS all four real vision MQTT channels',flush=True)
    finally:
        close(client)


if __name__=='__main__':
    main()
