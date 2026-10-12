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

REPAIR_CASES=[
    {'id':'availability-authority','question':'Kal 2 logo ke liye kamra milega?','language':'hinglish','expected_action':'RECEPTION'},
    {'id':'room-selection','question':'AC wala sabse sasta konsa hai?','language':'hinglish','actions':['ROOM_OPTIONS','ROOM_RATE','ANSWER'],'required':['Deluxe'],'forbidden':['Super Deluxe','Family Suite','Premium Window']},
    {'id':'failed-reception','question':'Bache ke liye cow milk milega?','language':'hinglish','expected_action':'RECEPTION'},
    {'id':'checkin-side-question','question':'Room ka rate kya hai?','language':'hinglish','pending':{'checkin_sessions':{'step':'NAME'}},'forbidden_action':'CHECKIN_DETAILS','unchanged_step':'NAME'},
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
            kwargs['allow_redirects']=False
            res=self.transport(url,*args,**kwargs)
            rec['status']=res.status_code
            body=res.json()
            candidate=(body.get('candidates') or [{}])[0]
            rec['response_text']=''.join(str(p.get('text','')) for p in (candidate.get('content') or {}).get('parts',[]) if not p.get('thought'))[:2500]
            rec['usage']=body.get('usageMetadata',{})
            if res.status_code!=200:
                self.stopped=True
                rec['error']=str((body.get('error') or {}).get('message',''))[:400]
            return res
        except Exception as exc:
            rec['error_type']=type(exc).__name__
            self.stopped=True
            raise

def contract_errors(case,plan,output,media_only=False):
    import re
    plan=plan or {};errors=[]
    language=case.get('language','hinglish' if 'actions' in case else None)
    if language and plan.get('language')!=language:errors.append('Wrong guest language')
    if not media_only and language=='hinglish' and (re.search(r'[\u0900-\u097F]',output) or not re.search(r'\b(ji|hai|hain|ki|ke|ka|mein|me|aur|mil|aap|chahiye|hoon|liye|nahi)\b',output,re.I)):
        errors.append('Final reply does not match Hinglish script/wording')
    if not media_only and language=='hindi' and not re.search(r'[\u0900-\u097F]',output):errors.append('Final reply does not match Hindi script')
    if case.get('scope') and plan.get('operation_text')!=case['scope']:errors.append('Wrong bill scope')
    if case.get('photo') and case['photo'].casefold() not in str(plan.get('photo_target','')).casefold():errors.append('Wrong photo target')
    if case.get('no_unrequested_price') and plan.get('show_prices'):errors.append('Unrequested price breakdown')
    return errors

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
    guest_payloads=[p for p in wire if p.get('to')==PHONE and p.get('type') in {'text','image','video','document','audio'}]
    text_payloads=[p for p in guest_payloads if p.get('type')=='text']
    media=[p for p in guest_payloads if p.get('type')!='text']
    output='\n'.join(p.get('text',{}).get('body','') if p.get('type')=='text' else p.get(p['type'],{}).get('caption','') for p in guest_payloads)
    whole_plan=next((t.get('plan') for t in trace if t.get('stage')=='conversation_plan'),None)
    if whole_plan:
        operations=whole_plan['operations']
        projected=operations[0] if operations else {'action':'ANSWER','confidence':1.0}
        plan=dict(projected,language=whole_plan['language'],questions=whole_plan['questions'],
                  script=whole_plan['script'],operations=operations)
    else:
        plan=next((p for p in plans if p),None)
    errors=[]
    if not plan:errors.append('No completed interpreter/review plan')
    if not output and not media:errors.append('No guest output')
    errors.extend(contract_errors(case,plan,output,media_only=bool(media and not text_payloads)))
    if case.get('photo') and media:
        configured=dict(bot.get_room_photo_categories())
        expected=next((url for name,url in configured.items() if name.casefold()==case['photo'].casefold()),None)
        if not expected or not any(p.get('image',{}).get('link')==expected for p in media):
            errors.append('Captured media does not match requested configured photo')
    if case.get('no_checkin_start') and after.get('checkin_sessions'):
        errors.append('Process enquiry started check-in')
    if case.get('expected_action') and (plan or {}).get('action')!=case['expected_action']:errors.append('Wrong action')
    if case.get('forbidden_action') and (plan or {}).get('action')==case['forbidden_action']:errors.append('Forbidden action')
    for forbidden in case.get('forbidden',[]):
        if forbidden in output: errors.append('Unrelated '+forbidden)
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
    call_records=copy.deepcopy(budget.calls[call_offset:])
    if plan and not fallback:
        for rec in call_records:rec.pop('response_text',None)
    return {'id':case['id'],'question':case['question'],'output':output,'guest_payloads':guest_payloads,'plan':plan,'errors':errors,
            'state_after':after,'memory':memory,'next_state':next_state,'trace':trace,'model_calls':call_records,'cumulative_calls':len(budget.calls),
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
    limit=max(1,min(750,int(os.getenv('AI_PRODUCTION_CHECK_LIMIT','12'))))
    connection=bot.requests.get('https://generativelanguage.googleapis.com/v1beta/models',headers={'x-goog-api-key':bot.GEMINI_API_KEY},timeout=18)
    listed=connection.status_code==200 and any(m.get('name')=='models/'+bot.GEMINI_MODEL for m in connection.json().get('models',[]))
    print('PRODUCTION EVAL CONNECTION: '+json.dumps({'run_id':run_id,'status':connection.status_code,'model':bot.GEMINI_MODEL,'configured_model_listed':listed}),flush=True)
    if not listed: return []
    budget=ModelBudget(bot.requests.post,limit=limit,interval=max(6,int(os.getenv('AI_PRODUCTION_CHECK_INTERVAL','15'))))
    print('PRODUCTION EVAL START: '+json.dumps({'run_id':run_id,'max_calls':limit,'mode':'synthetic guests; external mutations denied'}),flush=True)
    if os.getenv('AI_PRODUCTION_CHECK_SUITE')=='200':
        return run_conversations(bot,run_id,budget)
    rows=[]
    selected={x.strip() for x in os.getenv('AI_PRODUCTION_CHECK_CASE_IDS','').split(',') if x.strip()}
    for case in (REPAIR_CASES if os.getenv('AI_PRODUCTION_CHECK_SUITE')=='repairs' else CASES):
        if selected and case['id'] not in selected: continue
        row=evaluate(bot,case,live=True,budget=budget);row.pop('next_state',None);rows.append(row)
        print('PRODUCTION EVAL ROW: '+json.dumps(dict(row,run_id=run_id),ensure_ascii=False),flush=True)
        if budget.stopped or len(budget.calls)>=budget.limit or not row['plan']:break
    print('PRODUCTION EVAL END: '+json.dumps({'run_id':run_id,'calls':len(budget.calls),'rows':len(rows),'fresh_acceptance':sum(r['fresh_model_acceptance'] for r in rows)}),flush=True)
    return rows

def run_conversations(bot,run_id,budget):
    from qa_conversations import conversations
    rows=[]
    start_chat=max(1,min(20,int(os.getenv('AI_PRODUCTION_CHECK_START_CHAT','1'))))
    for chat in conversations()[start_chat-1:]:
        history=[]; state={}
        for index,turn in enumerate(chat['turns'],1):
            if budget.stopped or len(budget.calls)>=budget.limit: break
            case=dict(turn,id=f"{chat['id']}-{index:02}",question=turn['text'],guest=chat['guest'],history=history,raw_state=state)
            row=evaluate(bot,case,live=True,budget=budget)
            state=row.pop('next_state');history=row['memory']
            row['segment']=chat['segment'];rows.append(row)
            print('PRODUCTION EVAL ROW: '+json.dumps(dict(row,run_id=run_id),ensure_ascii=False),flush=True)
            if not row['model_calls']:break
        if budget.stopped or len(budget.calls)>=budget.limit or (rows and not rows[-1]['model_calls']):break
    print('PRODUCTION EVAL END: '+json.dumps({'run_id':run_id,'calls':len(budget.calls),'rows':len(rows),
        'fresh_acceptance':sum(r['fresh_model_acceptance'] for r in rows),'questions_in_suite':200,
        'start_chat':start_chat,'selected_questions':10*(21-start_chat),'not_run_in_selection':10*(21-start_chat)-len(rows)}),flush=True)
    return rows

def start(bot,run_id):
    import subprocess,sys,threading
    def worker():
        env=dict(os.environ,BOT_AUTOSTART='0',AI_PROVIDER_ORDER='gemini',AI_PRODUCTION_CHECK_RUN='')
        if os.getenv('AI_PRODUCTION_CHECK_MODEL','').strip():
            env['GEMINI_MODEL']=os.getenv('AI_PRODUCTION_CHECK_MODEL').strip()
        code='import app, hotel_eval; hotel_eval.run(app, '+repr(run_id)+')'
        try:subprocess.run([sys.executable,'-u','-c',code],env=env,timeout=60+35*max(1,min(750,int(env.get('AI_PRODUCTION_CHECK_LIMIT','12')))),check=False)
        except subprocess.TimeoutExpired:print('PRODUCTION EVAL STOP: worker timeout',flush=True)
    threading.Thread(target=worker,daemon=True).start()
