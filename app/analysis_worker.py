"""Independent local analytical worker. Never invokes satellite collection."""
import argparse
import logging
import os
import threading
from . import analysis_queue, analytical_assistant


def tick(worker_id=None):
    job=analysis_queue.claim(worker_id or 'local-'+str(os.getpid()))
    if not job:return False
    stop=threading.Event()
    def renew():
        while not stop.wait(30):
            if not analysis_queue.heartbeat(job['id'],job['lease_token']):break
    heartbeat=threading.Thread(target=renew,daemon=True);heartbeat.start()
    try:
        response=analytical_assistant.reply(job['payload'],job['tool'],work_id=job['id'])
        analysis_queue.complete(job['id'],job['lease_token'],response)
    except Exception:
        logging.exception('Local analytical job failed: %s',job['id'])
        response={'answer':'A análise local foi interrompida por uma falha interna.',
                  'work':{'id':job['id'],'status':'error'},'evidence_ids':[],'sources':[],
                  'limitations':[],'action':{'kind':'none','class_ids':[]}}
        analysis_queue.complete(job['id'],job['lease_token'],response)
    finally:
        stop.set();heartbeat.join(timeout=1)
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    stop=threading.Event()
    try:
        while True:
            worked=tick()
            if args.once:break
            if not worked:stop.wait(1)
    except KeyboardInterrupt:pass


if __name__=='__main__':main()
