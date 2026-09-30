"""Local administrator CLI. No public HTTP administration endpoint."""
import argparse
import json
import os
from reliability import Store

parser=argparse.ArgumentParser()
parser.add_argument('command',choices=['status','review','resolve-inbox'])
parser.add_argument('--id')
parser.add_argument('--confirmed-reviewed',action='store_true')
args=parser.parse_args()
path=os.getenv('BOT_DB_PATH')
if not path:
    parser.error('Set BOT_DB_PATH first')
store=Store(path)
if args.command=='status':
    print(json.dumps(store.diagnostics(),indent=2))
elif args.command=='review':
    # Contains identifiers/states only. Inspect the actual Sheet and WhatsApp before resolving.
    with store.db() as db:
        for table,states in [('inbox',"'review'"),('orders',"'unknown'"),('outbox',"'failed','unknown','unconfirmed'")]:
            print(table,json.dumps([dict(r) for r in db.execute(f'SELECT id,state FROM {table} WHERE state IN ({states})')]))
else:
    if not args.id or not args.confirmed_reviewed:
        parser.error('Provide --id and --confirmed-reviewed only after reconciling the actual action')
    with store.db() as db:
        count=db.execute("UPDATE inbox SET state='done' WHERE id=? AND state='review'",(args.id,)).rowcount
    print('Resolved records:',count,'(original action was not replayed)')
