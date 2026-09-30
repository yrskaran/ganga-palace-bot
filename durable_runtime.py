import hashlib
import json
import threading
import time
from types import SimpleNamespace

context = threading.local()


def request(app, payload):
    if not app.durable_store or payload.get('status') == 'read':
        return app._transport_request(payload)
    if not app.WHATSAPP_TOKEN or not app.PHONE_NUMBER_ID:
        return None
    # A customer turn gets its own key. Identical background alerts deduplicate per IST day.
    event = getattr(context,'event',None) or 'background:'+app.now_ist().date().isoformat()
    # send_whatsapp_message supplies a part index, so identical adjacent chunks
    # in a long answer are not mistaken for a duplicate delivery.
    part = getattr(context,'part',0)
    key=hashlib.sha256((event+str(part)+json.dumps(payload,sort_keys=True)).encode()).hexdigest()
    row=app.durable_store.enqueue_send(key,payload)
    if row['state'] in ('accepted','sent','delivered','read'):
        return SimpleNamespace(status_code=200)
    return transmit(app,key,payload)


def transmit(app,key,payload):
    store=app.durable_store
    if not store.claim_send(key):
        return None
    try:
        response=app._transport_request(payload)
        if response is None:
            store.send_result(key,'unknown')
            return None
        try:
            body=response.json()
        except (ValueError,AttributeError):
            body={}
        if response.status_code in (200,201):
            remote=(body.get('messages') or [{}])[0].get('id')
            store.send_result(key,'accepted' if remote else 'unknown',remote_id=remote)
        else:
            code=(body.get('error') or {}).get('code')
            state='retry' if response.status_code==429 else ('unknown' if response.status_code>=500 else 'failed')
            store.send_result(key,state,code=code)
        return response
    except Exception:
        store.send_result(key,'unknown')
        raise


def loop(app):
    while True:
        try:
            for row in app.durable_store.due_sends():
                transmit(app,row['id'],json.loads(row['body']))
            owner=app.format_whatsapp_number(app.OWNER_PHONE)
            if owner:
                for issue in app.durable_store.attention()[:5]:
                    # Never create an endless chain of failures notifying the same owner.
                    if issue['id'].startswith('outbox:'):
                        with app.durable_store.db() as db:
                            row=db.execute('SELECT body FROM outbox WHERE id=?',(issue['id'].split(':',1)[1],)).fetchone()
                        if row and json.loads(row['body']).get('to')==owner:
                            app.durable_store.mark_escalated(issue['id'])
                            continue
                    previous=getattr(context,'event',None)
                    context.event='escalation:'+issue['id']
                    try:
                        app.send_notification(owner,'Hotel bot needs review. Reference: '+issue['id']+'; status: '+issue['state']+'. Please verify before repeating the action.','OWNER')
                        # The owner send itself is recorded in the outbox, including failure.
                        app.durable_store.mark_escalated(issue['id'])
                    finally:
                        context.event=previous
        except Exception as exc:
            print('OUTBOX WORKER ERROR:',type(exc).__name__,flush=True)
        time.sleep(5)


def inbox_loop(app):
    while True:
        try:
            message=app.durable_store.next_message()
            if message:
                sender=message['from']
                context.event=message['id']
                success=False
                try:
                    app.queue_read_receipt(message['id'])
                    app.process_and_reply(message,sender,message.get('type',''))
                    success=True
                except Exception as exc:
                    print('INBOX REVIEW REQUIRED:',type(exc).__name__,flush=True)
                    app.send_whatsapp_message(sender,'Aapka request verify karna zaroori hai. Kripya reception se sampark karein; dobara order confirm karne se pehle status check kar lein.')
                finally:
                    app.durable_store.finish(message['id'],sender,app.session_snapshot(sender),success)
                    context.event=None
            else:
                time.sleep(0.5)
        except Exception as exc:
            context.event=None
            print('INBOX DATABASE ERROR:',type(exc).__name__,flush=True)
            time.sleep(2)


def append_order(app,room,name,details,amount):
    store=app.durable_store
    # Stable across a second confirmation message if the original response timed out.
    pending=next((sessions.get(app.turn_capture.current['phone']) for sessions in
        (app.duplicate_order_sessions,app.order_sessions)
        if getattr(app.turn_capture,'current',None) and sessions.get(app.turn_capture.current['phone'])),None)
    token=(pending or {}).get('created') or getattr(context,'event',None)
    if not token:
        raise ValueError('An order requires a durable confirmation event')
    body={'room':room,'name':name,'details':details,'amount':amount,'confirmation':token}
    key=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    state=store.order(key,body)
    if state=='saved':
        return True
    client=app.get_gspread_client()
    if not client:
        return False
    sheet=client.open_by_key(app.SHEET_ID).worksheet('Kitchen_Orders')
    rows=sheet.get_all_values()
    headers=rows[0] if rows else []
    if len(headers)<6:
        raise ValueError('Kitchen_Orders requires its six existing columns')
    matches=[i for i,h in enumerate(headers) if str(h).strip().upper()=='BOT ORDER ID']
    if len(matches)>1:
        raise ValueError('Duplicate BOT ORDER ID column')
    if matches:
        col=matches[0]
    else:
        col=max(len(headers),max((len(r) for r in rows),default=6))
        if col>=sheet.col_count:
            sheet.add_cols(col+1-sheet.col_count)
        sheet.update_cell(1,col+1,'BOT ORDER ID')
    if any(len(row)>col and row[col]==key for row in rows[1:]):
        store.order_state(key,'saved')
        return True
    # An absent ID after a timeout does not prove a delayed write will never arrive.
    if state in ('sending','unknown') or not store.claim_order(key):
        raise RuntimeError('Uncertain order write: reception reconciliation required')
    row=[app.now_ist().strftime('%d-%b-%Y %I:%M %p'),str(room),str(name),str(details),app.safe_int(amount),'PENDING']
    row+=['']*(col+1-len(row));row[col]=key
    try:
        sheet.append_row(row,value_input_option='RAW')
        store.order_state(key,'saved')
        with app.state_lock:
            app.shared_store.setdefault('kitchen_orders',[]).append(row)
        return True
    except Exception:
        store.order_state(key,'unknown')
        raise
