"""Run with an explicitly selected database/object provider; dry run by default."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/control'))


def reconcile_pending(*,apply=False,max_objects=100000):
    """Reconcile legacy workspaces; only a complete provider scan enables writes."""
    from sqlalchemy import select
    from studio.db import session_scope
    from studio.models import Workspace,StorageInventoryState
    from studio.storage import reconcile
    with session_scope() as db:
        workspace_ids=list(db.scalars(select(Workspace.id).where(
            ~select(StorageInventoryState.id).where(StorageInventoryState.workspace_id==Workspace.id).exists()
        ).order_by(Workspace.id).limit(1001)))
    if len(workspace_ids)>1000:
        raise RuntimeError('Reconcile larger inventories by explicit workspace ID')
    report={'workspaces':len(workspace_ids),'objects':0,'bytes':0,'untracked_objects':0,'applied':apply}
    for workspace_id in workspace_ids:
        result=reconcile(workspace_id,apply=apply,max_objects=max_objects)
        for key in ('objects','bytes','untracked_objects'):report[key]+=result[key]
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--workspace-id')
    target.add_argument('--pending',action='store_true',help='Scan workspaces missing their initial inventory')
    parser.add_argument('--max-objects',type=int,default=100000)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not 1<=args.max_objects<=10000000:parser.error('Use a bounded scan budget')
    from studio.storage import reconcile
    try:
        result=(reconcile_pending(apply=args.apply,max_objects=args.max_objects) if args.pending else
                reconcile(args.workspace_id,apply=args.apply,max_objects=args.max_objects))
    except Exception:
        raise SystemExit('Storage reconciliation failed; inspect protected operator logs. No credentials or object contents printed.') from None
    print(json.dumps(result))


if __name__=='__main__':main()
