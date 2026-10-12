"""Isolated, bounded comparison using the actual production AI stages."""
import copy
import json
import os
import time
from urllib.parse import urlparse

class CheckStopped(Exception):
    pass


class Budget:
    def __init__(self, post, limit=20, interval=15):
        self.send=post
        self.limit=limit
        self.interval=interval
        self.calls=0
        self.tokens=0
        self.stopped=False
        self.last=0
    def post(self,url,*args,**kwargs):
        if urlparse(url).hostname!='generativelanguage.googleapis.com' or self.stopped or self.calls>=self.limit:
            raise CheckStopped('No further request permitted')
        time.sleep(max(0,self.interval-(time.monotonic()-self.last)))
        self.calls+=1
        self.last=time.monotonic()
        response=self.send(url,*args,**kwargs)
        if response.status_code!=200:
            self.stopped=True
        else:
            self.tokens+=(response.json().get('usageMetadata') or {}).get('totalTokenCount',0)
        return response


def run(bot,run_id):
    import guest_checks
    from qa_runner import ChatState,execution_result
    if tuple(bot.AI_PROVIDER_ORDER)!=('gemini',):
        raise CheckStopped('Comparison requires an isolated Gemini-only process')
    selected={'02','03','12','26','32'}
    # Reserve the first failed availability call within the total20-call comparison.
    budget=Budget(bot.requests.post,limit=19)
    print('GEMINI CHECK START: '+json.dumps({'run_id':run_id,'model':bot.GEMINI_MODEL,
        'key_present':bool(bot.GEMINI_API_KEY),'max_calls':budget.limit,
        'cases':sorted(selected),'context':'fixed synthetic histories; real production interpreter/review/composer/critic; no operational writes'}),flush=True)
    if not bot.GEMINI_API_KEY:
        print('GEMINI CHECK BLOCKED: missing key',flush=True)
        return []
    response=bot.requests.get('https://generativelanguage.googleapis.com/v1beta/models',
        headers={'x-goog-api-key':bot.GEMINI_API_KEY},timeout=18)
    print('GEMINI CHECK CONNECTION: '+json.dumps({'status':response.status_code,
        'configured_model_listed':any(m.get('name')=='models/'+bot.GEMINI_MODEL for m in response.json().get('models',[])) if response.status_code==200 else False}),flush=True)
    if response.status_code!=200:
        return []
    old_post=bot.requests.post
    bot.requests.post=budget.post
    rows=[]
    try:
        for case in guest_checks.scenarios(False):
            if case['id'] not in selected:
                continue
            phone='919000000005'
            bot.conversation_memory[phone]=copy.deepcopy(case.get('history',[]))
            for name in ('checkin_sessions','order_sessions','duplicate_order_sessions','active_orders','service_guest_pending','reception_consent_sessions','reception_request_sessions'):
                getattr(bot,name).pop(phone,None)
            for name,value in case.get('pending',{}).items():
                getattr(bot,name)[phone]=dict(copy.deepcopy(value),created=time.time())
            plan=bot.understand_guest_request(case['text'],None,phone)
            errors=guest_checks.errors_for(case,plan,bot.CUSTOMER_CONFIG)
            reply=''
            source=''
            if isinstance(plan,dict) and plan.get('action'):
                chat=ChatState({'id':'G-'+case['id'],'guest':None})
                chat.pending=copy.deepcopy(case.get('pending',{}))
                source=execution_result(chat,plan,bot.CUSTOMER_CONFIG,bot)
                rendered=dict(case,source=source)
                reply=guest_checks.render(bot,rendered,plan)
                if not bot._ai_content_is_usable(reply,'Gemini check'):
                    errors.append('Missing or unusable actual reply')
            else:
                errors.append('No completed actual-model plan')
            row={'id':case['id'],'run_id':run_id,'code_revision':os.getenv('RENDER_GIT_COMMIT','unknown'),
                'question':case['text'],'history':case.get('history',[]),'plan':plan,'reply':reply,
                'source':source,'errors':errors,'calls':budget.calls,'total_tokens':budget.tokens,
                'provider':'gemini','model':bot.GEMINI_MODEL,'execution':'No WhatsApp/Sheets/order/payment writes; isolated result receipts'}
            rows.append(row)
            print('GEMINI CHECK ROW: '+json.dumps(row,ensure_ascii=False),flush=True)
            if budget.stopped or not plan or budget.calls>=budget.limit:
                break
    finally:
        bot.requests.post=old_post
    print('GEMINI CHECK SUMMARY: '+json.dumps({'run_id':run_id,'completed':len(rows),
        'calls':budget.calls,'total_tokens':budget.tokens,'blocked':budget.stopped}),flush=True)
    return rows


if __name__=='__main__':
    os.environ['BOT_AUTOSTART']='0'
    os.environ['AI_PROVIDER_ORDER']='gemini'
    import app
    run(app,os.environ.get('AI_GUEST_CHECK_RUN','gemini-comparison'))
