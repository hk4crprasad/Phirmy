"""Review/queue/resume a bounded key migration. Never prints key material.

Configure a NEW active key ID/material securely on every writer first. Preserve
APP_SECRET and all historical keys. Run --queue to create a durable job; the
dedicated worker executes it. --run-one-batch is useful for isolated maintenance.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',action='store_true');parser.add_argument('--target-key-id')
    parser.add_argument('--workspace-id');parser.add_argument('--run-one-batch',action='store_true')
    parser.add_argument('--resume-job');args=parser.parse_args()
    try:
        from sqlalchemy import select
        from studio.db import session_scope,as_dict
        from studio.key_provider import get_provider
        from studio.key_rotation import queue_rotation,process_rotation_batch
        from studio.models import CipherRotationJob,CipherRotationAudit
        if args.queue:
            if not args.target_key_id:parser.error('--queue requires the exact --target-key-id')
            with session_scope(write=True) as db:
                job=queue_rotation(db,args.target_key_id,'local-operator',args.workspace_id)
                print(json.dumps({'queued_job_id':job.id,'target_key_id':job.target_key_id}))
        elif args.resume_job:
            with session_scope(write=True) as db:
                job=db.get(CipherRotationJob,args.resume_job,with_for_update=True)
                if not job or job.state not in {'paused','blocked'}:raise ValueError('Job cannot resume')
                if job.target_key_id!=get_provider().active_key_id():raise ValueError('Active key changed')
                job.state='queued';job.error={};db.add(CipherRotationAudit(job_id=job.id,event='resumed',data={'actor':'local-operator'}))
                print(json.dumps({'resumed_job_id':job.id}))
        elif args.run_one_batch:print(json.dumps({'processed_batch':process_rotation_batch()}))
        else:
            with session_scope() as db:
                print(json.dumps({'active_key_id':get_provider().active_key_id(),
                    'jobs':[as_dict(job) for job in db.scalars(select(CipherRotationJob).order_by(CipherRotationJob.created_at.desc()).limit(20))]}))
    except Exception as error:
        print('Encryption maintenance failed:',type(error).__name__)
        raise SystemExit(1)


if __name__=='__main__':main()
