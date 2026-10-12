"""Production-entry evaluation with synthetic guests and denied external mutations.

Model expectations are assertion metadata, never included in prompts. This is
conversation acceptance with isolated I/O, not proof of real staff delivery.
"""
import copy
import json
import os
import time
from contextlib import ExitStack
from unittest.mock import Mock, patch
from urllib.parse import urlparse

PHONE='919000000005'
SESSION_NAMES=('order_sessions','duplicate_order_sessions','checkin_sessions','active_orders','demo_food_sessions','demo_guest_sessions','service_guest_pending','service_tasks_by_id','service_sessions','reception_consent_sessions','reception_request_sessions','reception_requests_by_id','reception_requests_by_alert','photo_sessions')
CASES=[
    {'id':'followup-price','question':'Kitne ki hai?',
     'history':[{'role':'user','content':'Standard veg thali bhi hai?'},
                {'role':'assistant','content':'Standard Veg Thali menu mein hai.'}],
     'language':'hinglish','expected_action':'MENU_ITEM_INFO','required':['Standard Veg Thali','200']},
    {'id':'tea-options','question':'Chai me kya kya option hai',
     'language':'hinglish','expected_action':'MENU_ITEM_INFO','required':['Cutting Chai','Masala Chai']},
    {'id':'own-room','question':"What's my room number?",'language':'english',
     'guest':{'name':'Synthetic Guest','room':'240','status':'CHECKED_IN','is_inhouse':True},
     'expected_action':'ANSWER','required':['240']},
    {'id':'checkin-side-question','question':'Room ka rate kya hai?',
     'pending':{'checkin_sessions':{'step':'NAME','created':0}},
     'forbidden_action':'CHECKIN_DETAILS','unchanged_step':'NAME'},
]

class BlockedIO(RuntimeError): pass

class ModelBudget:
    def __init__(self, transport, limit=12, interval=15):
        self.transport=transport; self.limit=limit; self.interval=interval
        self.calls=[]; self.last=0; self.stopped=False
    def post(self,url,*args,**kwargs):
        if urlparse(url).hostname!='generativelanguage.googleapis.com':
            raise BlockedIO('External mutation denied')
        if self.stopped or len(self.calls)>=self.limit:
            raise BlockedIO('Model budget stopped')
        time.sleep(max(0,self.interval-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        rec={'provider':'gemini','status':None};self.calls.append(rec)
        try:
            res=self.transport(url,*args,**kwargs)
            rec['status']=res.status_code
            body=res.json()
            rec['usage']=body.get('usageMetadata',{})
            if res.status_code!=200:
                self.stopped=True
                rec['error']=str((body.get('error') or {}).get('message',''))[:400]
            return res
        except Exception:
            self.stopped=True
            raise

def evaluate(bot,case,transport=None,live=False,budget=None):
    """Run actual interpreter/review/dispatch/composer and wire-message memory."""
    import ai_receptionist as ai
    plans=[];wire=[];trace=[]
    call_offset=len(budget.calls) if budget is not None else 0
    real_session_request=bot.requests.sessions.Session.request
    real_understand=bot.understand_guest_request
    def understand(*args,**kwargs):
        result=real_understand(*args,**kwargs);plans.append(copy.deepcopy(result));return result
    def send(payload,*args,**kwargs):
        wire.append(copy.deepcopy(payload))
        return Mock(status_code=200,json=Mock(return_value={'messages':[{'id':'eval-isolated'}]}))
    def denied(*args,**kwargs): raise BlockedIO('External I/O denied')
    def guarded_session(session,method,url,*args,**kwargs):
        if live and method.upper()=='POST' and urlparse(url).hostname=='generativelanguage.googleapis.com':
            return real_session_request(session,method,url,*args,**kwargs)
        raise BlockedIO('External network operation denied')
    guest=case.get('guest')
    config=copy.deepcopy(bot.CUSTOMER_CONFIG);config['ai_receptionist_flow']=True;config['demo_mode']=False
    token=ai.evaluation.set(trace)
    try:
        with ExitStack() as stack:
            values={'CUSTOMER_CONFIG':config,'CUSTOMER_DEMO_MODE':False,'conversation_memory':{PHONE:copy.deepcopy(case.get('history',[]))},
                'guest_language_cache':{},'shared_store':{'last_synced':time.time(),'complaint_headers':[],'complaint_rows':[]},
                'durable_store':None,'get_guest_stay_status':Mock(return_value=guest),'get_gspread_client':Mock(return_value=None),
                'fetch_sheet_data_sync':Mock(return_value=False),'refresh_staff_roster':Mock(),
                'whatsapp_request':send,'understand_guest_request':understand,
                'send_staff_alert':Mock(return_value=False),'send_reception_alert':Mock(return_value=(False,None,None))}
            for name in SESSION_NAMES:
                values[name]={}
            for name,value in case.get('pending',{}).items():
                value=copy.deepcopy(value)
                if isinstance(value,dict): value['created']=time.time()
                values[name]={PHONE:value}
            for name,value in case.get('raw_state',{}).items():
                if name in SESSION_NAMES: values[name]=copy.deepcopy(value)
            for name,value in values.items():stack.enter_context(patch.object(bot,name,value))
            if budget is None: budget=ModelBudget(transport or bot.requests.post,limit=12,interval=15 if live else 0)
            stack.enter_context(patch.object(bot.requests,'post',budget.post))
            stack.enter_context(patch.object(bot.requests,'get',denied))
            # SDK transports must also be denied; configured provider is Gemini only.
            stack.enter_context(patch.object(bot.requests.sessions.Session,'request',guarded_session))
            stack.enter_context(patch.object(bot,'_ai_provider_functions',return_value=[('gemini',bot.ask_gemini_chat)]))
            stack.enter_context(patch.object(bot,'AI_PROVIDER_ORDER',('gemini',)))
            stack.enter_context(patch.object(bot,'_gemini_circuit_open',return_value=False))
            bot.process_and_reply({'id':'eval-'+case['id'],'type':'text','text':{'body':case['question']}},PHONE,'text')
            after=copy.deepcopy(ai.snapshot(bot,PHONE))
            memory=copy.deepcopy(bot.conversation_memory.get(PHONE,[]))
            next_state={name:copy.deepcopy(getattr(bot,name)) for name in SESSION_NAMES}
    finally:ai.evaluation.reset(token)
    output='\n'.join(p.get('text',{}).get('body','') for p in wire if p.get('to')==PHONE and p.get('type')=='text')
    plan=next((p for p in plans if p),None)
    errors=[]
    if not plan:errors.append('No completed interpreter/review plan')
    if not output:errors.append('No guest output')
    if case.get('language') and (plan or {}).get('language')!=case['language']:errors.append('Wrong guest language')
    if case.get('language')=='hinglish':
        import re
        if re.search(r'[\u0900-\u097F]',output) or not re.search(r'\b(ji|hai|hain|ki|ke|ka|mein|me|aur|mil|aap|chahiye)\b',output,re.I):
            errors.append('Final reply does not match Hinglish script/wording')
    if case.get('expected_action') and (plan or {}).get('action')!=case['expected_action']:errors.append('Wrong action')
    if case.get('forbidden_action') and (plan or {}).get('action')==case['forbidden_action']:errors.append('Forbidden action')
    for required in case.get('required',[]):
        if required not in output:errors.append('Missing '+required)
    if case.get('unchanged_step') and after.get('checkin_sessions',{}).get('step')!=case['unchanged_step']:errors.append('Check-in step advanced')
    fallback=any(t.get('outcome')=='verified_backend_fallback' for t in trace)
    if fallback:errors.append('Verified-data fallback; fresh AI wording not accepted')
    if 'actions' in case:
        import guest_checks
        errors.extend(guest_checks.errors_for(dict(case,text=case['question']),plan,config))
        for value in case.get('contains',[]):
            if value not in output: errors.append('Missing '+value)
    return {'id':case['id'],'question':case['question'],'output':output,'plan':plan,'errors':errors,
            'state_after':after,'memory':memory,'next_state':next_state,'trace':trace,'model_calls':copy.deepcopy(budget.calls[call_offset:]),'cumulative_calls':len(budget.calls),
            'provenance':'fresh_model' if live else 'offline_transport_double',
            'fresh_model_acceptance':bool(live and not errors),'external_io':'isolated; no real WhatsApp, Sheets, orders or payments',
            'revision':os.getenv('RENDER_GIT_COMMIT','local'),'model':bot.GEMINI_MODEL}

def call_api(prompt,options=None,context=None):
    os.environ['BOT_AUTOSTART']='0'
    import app
    case={'id':'promptfoo','question':prompt}
    row=evaluate(app,case,live=True)
    return {'output':row['output'],'metadata':row}

def run(bot,run_id):
    limit=max(1,min(40,int(os.getenv('AI_PRODUCTION_CHECK_LIMIT','12'))))
    connection=bot.requests.get('https://generativelanguage.googleapis.com/v1beta/models',headers={'x-goog-api-key':bot.GEMINI_API_KEY},timeout=18)
    listed=connection.status_code==200 and any(m.get('name')=='models/'+bot.GEMINI_MODEL for m in connection.json().get('models',[]))
    print('PRODUCTION EVAL CONNECTION: '+json.dumps({'run_id':run_id,'status':connection.status_code,'model':bot.GEMINI_MODEL,'configured_model_listed':listed}),flush=True)
    if not listed: return []
    budget=ModelBudget(bot.requests.post,limit=limit,interval=15)
    print('PRODUCTION EVAL START: '+json.dumps({'run_id':run_id,'max_calls':limit,'mode':'synthetic guests; external mutations denied'}),flush=True)
    if os.getenv('AI_PRODUCTION_CHECK_SUITE')=='200':
        return run_conversations(bot,run_id,budget)
    rows=[]
    for case in CASES:
        row=evaluate(bot,case,live=True,budget=budget);row.pop('next_state',None);rows.append(row)
        print('PRODUCTION EVAL ROW: '+json.dumps(dict(row,run_id=run_id),ensure_ascii=False),flush=True)
        if budget.stopped or len(budget.calls)>=budget.limit or not row['plan']:break
    print('PRODUCTION EVAL END: '+json.dumps({'run_id':run_id,'calls':len(budget.calls),'rows':len(rows),'fresh_acceptance':sum(r['fresh_model_acceptance'] for r in rows)}),flush=True)
    return rows

def run_conversations(bot,run_id,budget):
    from qa_conversations import conversations
    rows=[]
    for chat in conversations():
        history=[]; state={}
        for index,turn in enumerate(chat['turns'],1):
            if budget.stopped or len(budget.calls)>=budget.limit: break
            case=dict(turn,id=f"{chat['id']}-{index:02}",question=turn['text'],guest=chat['guest'],history=history,raw_state=state)
            row=evaluate(bot,case,live=True,budget=budget)
            state=row.pop('next_state');history=row['memory']
            row['segment']=chat['segment'];rows.append(row)
            print('PRODUCTION EVAL ROW: '+json.dumps(dict(row,run_id=run_id),ensure_ascii=False),flush=True)
            if not row['plan']:break
        if budget.stopped or len(budget.calls)>=budget.limit or (rows and not rows[-1]['plan']):break
    print('PRODUCTION EVAL END: '+json.dumps({'run_id':run_id,'calls':len(budget.calls),'rows':len(rows),
        'fresh_acceptance':sum(r['fresh_model_acceptance'] for r in rows),'questions_in_suite':200,'not_run':200-len(rows)}),flush=True)
    return rows

def start(bot,run_id):
    import subprocess,sys,threading
    def worker():
        env=dict(os.environ,BOT_AUTOSTART='0',AI_PROVIDER_ORDER='gemini',AI_PRODUCTION_CHECK_RUN='')
        if os.getenv('AI_PRODUCTION_CHECK_MODEL','').strip():
            env['GEMINI_MODEL']=os.getenv('AI_PRODUCTION_CHECK_MODEL').strip()
        code='import app, hotel_eval; hotel_eval.run(app, '+repr(run_id)+')'
        try:subprocess.run([sys.executable,'-u','-c',code],env=env,timeout=60+35*max(1,min(40,int(env.get('AI_PRODUCTION_CHECK_LIMIT','12')))),check=False)
        except subprocess.TimeoutExpired:print('PRODUCTION EVAL STOP: worker timeout',flush=True)
    threading.Thread(target=worker,daemon=True).start()
