"""Single-process SQLite inbox, sessions, order ledger and delivery outbox.

Persist this file on a durable volume. Unknown remote outcomes are quarantined,
not automatically retried: neither Sheets append nor Meta send is transactional.
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS inbox (
                  id TEXT PRIMARY KEY, sender TEXT NOT NULL, body TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  sender TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                  id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                  id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                  remote_id TEXT UNIQUE, attempts INTEGER NOT NULL DEFAULT 0,
                  due REAL NOT NULL DEFAULT 0, code TEXT, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS delivery_events (
                  remote_id TEXT PRIMARY KEY, status TEXT NOT NULL, codes TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS escalations (
                  id TEXT PRIMARY KEY, created REAL NOT NULL);
            ''')
            # Existing databases retain all rows. Historic timestamps are only
            # last-known activity; new messages keep immutable creation times.
            if 'created' not in {r['name'] for r in db.execute('PRAGMA table_info(outbox)')}:
                db.execute('ALTER TABLE outbox ADD COLUMN created REAL')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE inbox SET state='review' WHERE state='processing'")
            db.execute("UPDATE outbox SET state='unknown' WHERE state='sending'")
            db.execute("UPDATE orders SET state='unknown' WHERE state='sending'")

    def enqueue(self, message):
        with self.db() as db:
            return db.execute('INSERT OR IGNORE INTO inbox(id,sender,body,created) VALUES(?,?,?,?)',
                (message['id'], message['from'], json.dumps(message), time.time())).rowcount == 1

    def next_message(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Hold later turns for a sender whose interrupted turn needs review.
            row = db.execute("""SELECT * FROM inbox i WHERE state='queued' AND NOT EXISTS
              (SELECT 1 FROM inbox p WHERE p.sender=i.sender AND p.state IN ('processing','review'))
              ORDER BY created,rowid LIMIT 1""").fetchone()
            if not row:
                return None
            db.execute("UPDATE inbox SET state='processing' WHERE id=?", (row['id'],))
            return json.loads(row['body'])

    def finish(self, message_id, sender, snapshot, success):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',
                (sender,json.dumps(snapshot),time.time()))
            db.execute('UPDATE inbox SET state=? WHERE id=?',('done' if success else 'review',message_id))

    def sessions(self):
        with self.db() as db:
            return {r['sender']:json.loads(r['body']) for r in db.execute('SELECT * FROM sessions')}

    def order(self, key, body):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?)',
                (key,json.dumps(body),'prepared',time.time()))
            return db.execute('SELECT state FROM orders WHERE id=?',(key,)).fetchone()['state']

    def claim_order(self, key):
        with self.db() as db:
            return db.execute("UPDATE orders SET state='sending',updated=? WHERE id=? AND state='prepared'",
                (time.time(),key)).rowcount == 1

    def order_state(self,key,state):
        with self.db() as db:
            db.execute('UPDATE orders SET state=?,updated=? WHERE id=?',(state,time.time(),key))

    def enqueue_send(self,key,payload):
        with self.db() as db:
            now = time.time()
            db.execute('INSERT OR IGNORE INTO outbox(id,body,updated,created) VALUES(?,?,?,?)',
                (key,json.dumps(payload),now,now))
            return dict(db.execute('SELECT * FROM outbox WHERE id=?',(key,)).fetchone())

    def claim_send(self,key):
        with self.db() as db:
            return db.execute("""UPDATE outbox SET state='sending',attempts=attempts+1,updated=?
                WHERE id=? AND state IN ('queued','retry') AND due<=? AND attempts<3""",
                (time.time(),key,time.time())).rowcount == 1

    def send_result(self,key,state,remote_id=None,code=None):
        with self.db() as db:
            row=db.execute('SELECT attempts FROM outbox WHERE id=?',(key,)).fetchone()
            if state=='retry' and row['attempts']>=3:
                state='failed'
            db.execute('UPDATE outbox SET state=?,remote_id=COALESCE(?,remote_id),code=?,due=?,updated=? WHERE id=?',
                (state,remote_id,str(code or ''),time.time()+60*max(1,row['attempts']),time.time(),key))
            early=db.execute('SELECT * FROM delivery_events WHERE remote_id=?',(remote_id,)).fetchone() if remote_id else None
        if early:
            self.delivery(remote_id,early['status'],json.loads(early['codes']))

    def delivery(self,remote_id,status,codes):
        if status not in {'sent','delivered','read','failed'}:
            return
        with self.db() as db:
            prior=db.execute('SELECT status FROM delivery_events WHERE remote_id=?',(remote_id,)).fetchone()
            if prior and prior['status'] in ('delivered','read') and status in ('sent','failed'):
                return
            if prior and prior['status']=='read' and status=='delivered':
                return
            db.execute('INSERT OR REPLACE INTO delivery_events VALUES(?,?,?)',(remote_id,status,json.dumps(codes)))
            row=db.execute('SELECT * FROM outbox WHERE remote_id=?',(remote_id,)).fetchone()
            if not row:
                return
            rank={'accepted':0,'sent':1,'delivered':2,'read':3}
            if row['state'] in {'delivered','read'} and (status=='failed' or rank.get(status,0)<=rank[row['state']]):
                return
            # Failed delivery means Meta says no delivery occurred. Retry only explicit transient codes.
            state='retry' if status=='failed' and any(c in (130429,131000,131016) for c in codes) and row['attempts']<3 else status
            db.execute('UPDATE outbox SET state=?,code=?,due=?,updated=? WHERE id=?',
                (state,json.dumps(codes),time.time()+60,time.time(),row['id']))

    def due_sends(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM outbox WHERE state IN ('queued','retry') AND due<=? AND attempts<3 ORDER BY updated LIMIT 10",(time.time(),))]

    def diagnostics(self):
        with self.db() as db:
            return {table:{r['state']:r['n'] for r in db.execute(f'SELECT state,COUNT(*) n FROM {table} GROUP BY state')}
                for table in ('inbox','orders','outbox')}

    def attention(self):
        with self.db() as db:
            db.execute("UPDATE outbox SET state='unconfirmed' WHERE state IN ('accepted','sent') AND updated<?",(time.time()-1800,))
            rows=[]
            for table, states in [('inbox',"'review'"),('orders',"'unknown'"),('outbox',"'failed','unknown','unconfirmed'")]:
                for row in db.execute(f"SELECT id,state FROM {table} WHERE state IN ({states}) LIMIT 50"):
                    key=table+':'+row['id']
                    if not db.execute('SELECT 1 FROM escalations WHERE id=?',(key,)).fetchone():
                        rows.append({'id':key,'state':row['state']})
            return rows

    def mark_escalated(self,key):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO escalations VALUES(?,?)',(key,time.time()))
