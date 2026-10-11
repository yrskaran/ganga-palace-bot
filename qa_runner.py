"""Opt-in batched real-AI conversation QA. No external operational writes.

Shared production interpretation policy, independent synthetic state and actual
reply history. This is diagnostic batching, not a real WhatsApp E2E test.
"""
import copy
import json
import os
import re
import threading
import time
import ai_receptionist as ai
import demo_food
from qa_conversations import conversations
from guest_checks import errors_for


def batch_rows(obj, ids):
    rows = obj.get('results') if isinstance(obj, dict) else None
    if not isinstance(rows, list) or len(rows) != len(ids):
        return None
    if any(not isinstance(row, dict) for row in rows):
        return None
    keys = [row.get('id') for row in rows]
    if len(set(keys)) != len(keys) or set(keys) != set(ids):
        return None
    return {row['id']: row for row in rows}


class ChatState:
    def __init__(self, chat):
        self.chat = chat
        self.history = []
        self.pending = {}
    def remember(self, question, reply):
        self.history.extend([{'role':'user','content':question},
                             {'role':'assistant','content':reply}])


def execution_result(chat, plan, config, bot=None):
    """Receipts derived from actual plan, never from expected test answers."""
    action = str(plan.get('action') or '')
    menu = {row['name']:row for row in config.get('menu', [])}
    if action == 'MENU_ITEM_INFO':
        items = plan.get('items') or []
        if not items or any(i.get('name') not in menu for i in items):
            return 'No valid configured menu items were selected. No order created.'
        return '\n'.join(f"{i['name']} — ₹{menu[i['name']]['price']}" if plan.get('show_prices') else f"• {i['name']}" for i in items)
    if action == 'SHOW_MENU':
        section = plan.get('menu_section', '').upper()
        if bot is None:
            return 'Production read-only menu renderer not available.'
        if section == 'FULL':
            cards=bot._full_menu_presentation_messages(include_prices=plan.get('show_prices') is True,sender_phone='')
        else:
            cards=[bot._menu_section_message(section,include_prices=plan.get('show_prices') is True,sender_phone='',include_cta=False)]
        return '\n\n'.join(cards)
    if action in {'ORDER','ORDER_SELECTION'}:
        if not (chat.chat.get('guest') or {}).get('is_inhouse'):
            return 'No verified active stay for this sender. No cart or order created; reception must verify check-in.'
        items = plan.get('items') or []
        if not items or any(i.get('name') not in menu or type(i.get('qty')) is not int or not 1 <= i['qty'] <= 50 for i in items):
            return 'No valid complete items and quantities supplied. No cart created or changed. Ask a focused clarification.'
        total = sum(menu[i['name']]['price']*i['qty'] for i in items)
        lines = [f"{i['qty']} x {i['name']} — ₹{menu[i['name']]['price']*i['qty']}" for i in items]
        chat.pending['order_sessions'] = {'items':copy.deepcopy(items),'order':' + '.join(lines),'total':total,'state':'PENDING_CONFIRMATION'}
        return '\n'.join(lines)+f'\nTotal: ₹{total}\nPending cart saved. Fresh explicit confirmation required. No kitchen dispatch or payment verified.'
    if action == 'ORDER_CONFIRM':
        cart = chat.pending.pop('order_sessions', None)
        if not cart:
            return 'No saved pending cart exists. No order confirmed. Ask which items and quantities are intended.'
        chat.pending['active_orders'] = dict(cart, order_id='QA-'+chat.chat['id'],state='CONFIRMED')
        return f"Order saved: {cart['order']}\nTotal: ₹{cart['total']}\nOrder ID: QA-{chat.chat['id']}\nKitchen notification delivery failed. No food delivery or payment confirmed."
    if action == 'ORDER_DECLINE':
        chat.pending.pop('order_sessions',None)
        return 'Pending cart cleared. No new order confirmed; existing confirmed orders unchanged.'
    if action == 'ORDER_CANCEL':
        order = chat.pending.get('active_orders')
        return 'Cancellation requested for saved order; staff cancellation not yet confirmed.' if order else 'No saved confirmed order exists to cancel.'
    if action == 'RECEPTION_DECLINE':
        chat.pending.pop('reception_consent_sessions',None)
        return 'Proposed reception contact declined. No new staff message sent.'
    if action == 'RECEPTION' or plan.get('needs_reception'):
        request = plan.get('reception_request') or plan.get('operation_text')
        if not request:
            return 'No complete reception question supplied. No staff message sent.'
        if not plan.get('reception_followup'):
            chat.pending['reception_consent_sessions'] = {'request':request,'status':'DELIVERY_FAILED'}
        return 'Reception question recorded locally: '+request+'. WhatsApp delivery to reception failed. No staff confirmation received. No new order or booking created.'
    if action in {'SERVICE','COMPLAINT'}:
        if not (chat.chat.get('guest') or {}).get('is_inhouse'):
            return 'No verified active stay. No staff request sent.'
        details = plan.get('operation_text') or plan.get('service')
        chat.pending['service_guest_pending'] = {'task_id':'QA-T-'+chat.chat['id'],'details':details,'status':'PENDING'}
        return 'Request recorded locally: '+str(details)+'. Staff notification delivery failed. Completion and arrival time not confirmed.'
    if action in {'SERVICE_FEEDBACK','COMPLAINT_FEEDBACK'}:
        task = chat.pending.get('service_guest_pending')
        if not task:
            return 'No pending completion feedback request is verified. No task closed.'
        return 'Guest feedback recorded for '+task['task_id']+': '+str(plan.get('operation_text'))+'. No staff completion independently verified.'
    if action == 'BILL':
        if not chat.chat.get('guest'):
            return 'No verified sender stay. No bill retrieved.'
        scope = plan.get('operation_text','full')
        data = {'food':'Food charges: ₹210','room':'Room charges: ₹1999','full':'Room charges: ₹1999\nFood charges: ₹210\nTotal: ₹2209\nPayments received: ₹0\nOutstanding: ₹2209'}
        return 'Verified synthetic sender bill, Room 240:\n'+data.get(scope,data['full'])
    if action == 'ROOM_OPTIONS':
        return '\n'.join(row['name']+(f" — starting ₹{row['price']}" if plan.get('show_prices') else '')+': '+row.get('details','') for row in config.get('rooms',[]))+'\nLive room stock and final booking rate not verified.'
    if action == 'SHOW_PHOTO':
        return 'Photo selection: '+str(plan.get('photo_target',''))+'. Media delivery not executed in this diagnostic. Do not claim a photo was sent.'
    if action.startswith('CHECKIN'):
        return 'Check-in request requires verified identity and reception review. No verified stay or room allocation created. No OTP sent in this diagnostic.'
    return ''


class Transport:
    def __init__(self, bot):
        self.bot = bot
        self.blocked = set()
        self.models = list(dict.fromkeys([bot.get_active_groq_model(), bot.GROQ_FALLBACK_CHAT_MODEL,'qwen/qwen3.8-27b']))
        self.usage = 0
    def call(self, prompt, ids, stage):
        for model in self.models:
            if not model or model in self.blocked:
                continue
            with self.bot.GROQ_LOCK:
                if time.time() < self.bot.GROQ_MODEL_UNAVAILABLE_UNTIL.get(model,0):
                    continue
            payload = {'model':model,'messages':[{'role':'system','content':'Hotel receptionist diagnostic. Keep cases strictly independent. Return JSON only.'},{'role':'user','content':prompt}],
                       'temperature':0.1,'response_format':{'type':'json_object'},'max_completion_tokens':min(3000,600*len(ids))}
            if 'gpt-oss' in model:
                payload.update(reasoning_effort='low',include_reasoning=False)
            elif 'qwen3.8' in model:
                payload['reasoning_effort']='none'
            for attempt in range(2):
                started=time.monotonic()
                try:
                    response = self.bot.requests.post('https://api.groq.com/openai/v1/chat/completions',headers={'Authorization':'Bearer '+self.bot.GROQ_API_KEY,'Content-Type':'application/json'},json=payload,timeout=55)
                except self.bot.requests.RequestException:
                    print('HOTEL QA PROVIDER ERROR: '+json.dumps({'model':model,'stage':stage,'type':'network'}),flush=True)
                    break
                if response.status_code == 429:
                    detail = response.text.lower()
                    daily = 'tokens per day' in detail or 'tpd' in detail
                    if daily:
                        self.blocked.add(model)
                        print('HOTEL QA LIMIT: '+json.dumps({'model':model,'stage':stage,'type':'daily'}),flush=True)
                        break
                    if attempt == 0:
                        time.sleep(55)
                        continue
                    print('HOTEL QA LIMIT: '+json.dumps({'model':model,'stage':stage,'type':'rate'}),flush=True)
                    break
                if response.status_code != 200:
                    print('HOTEL QA PROVIDER ERROR: '+json.dumps({'model':model,'status':response.status_code,'stage':stage}),flush=True)
                    break
                body=response.json()
                tokens=body.get('usage',{}).get('total_tokens',0)
                self.usage += tokens
                raw=body['choices'][0]['message'].get('content','')
                rows=batch_rows(self.bot._parse_ai_json(raw),ids)
                print('HOTEL QA USAGE: '+json.dumps({'model':model,'stage':stage,'tokens':tokens,'total':self.usage,'valid':bool(rows)}),flush=True)
                # Pace to diagnostic 6K TPM, leaving headroom for real guests.
                time.sleep(max(0,min(55,tokens/100-(time.monotonic()-started))))
                if rows:
                    return rows,model
                if attempt:
                    break
        return None,None


def recent(history):
    result=[]
    budget=1800
    for row in reversed(history[-8:]):
        value=str(row['content'])
        if len(value)>budget:
            value=value[-budget:]
        if not value:
            break
        result.append({'role':row['role'],'content':value})
        budget-=len(value)
        if budget<=0:
            break
    return list(reversed(result))


def run(bot, run_id):
    chats=[ChatState(c) for c in conversations()]
    config=bot.CUSTOMER_CONFIG
    transport=Transport(bot)
    policy=ai.interpretation_prompt(bot,'<provided separately in each case>',None,None,'<per-case verified session state>')
    facts={k:config.get(k) for k in ('hotel','rooms','room_rules','policies','faq','local_guide','maps')}
    rows=[]
    for turn_index in range(10):
        for offset in range(0,len(chats),4):
            group=chats[offset:offset+4]
            cases=[]
            for chat in group:
                turn=chat.chat['turns'][turn_index]
                cases.append({'id':f"{chat.chat['id']}-{turn_index+1:02}",'message':turn['text'],'guest':chat.chat['guest'],'verified_session_state':copy.deepcopy(chat.pending),'recent_dialogue':recent(chat.history)})
            ids=[c['id'] for c in cases]
            prompt=policy+'\nShared verified hotel facts: '+json.dumps(facts,ensure_ascii=False)+'\nApply identical instructions independently to EACH case below. The placeholder Guest:null in the shared policy is replaced by each case guest. Return {"results":[{"id":"case ID", ...all interpretation fields...}]}. No case may borrow another case context.\nCases: '+json.dumps(cases,ensure_ascii=False)
            plans,model=transport.call(prompt,ids,'interpret')
            outputs={}
            sources={}
            compose_cases=[]
            for chat,case in zip(group,cases):
                plan=(plans or {}).get(case['id'])
                if plan:
                    try:
                        source=execution_result(chat,plan,config,bot)
                    except (TypeError,ValueError,KeyError,AttributeError):
                        source='Invalid action arguments. No operation executed.'
                        plan['qa_execution_error']=True
                    sources[case['id']]=source
                    if source:
                        compose_cases.append({'id':case['id'],'message':case['message'],'language':plan.get('language'),'understanding':plan.get('understood_as'),'verified_result':source})
                    else:
                        outputs[case['id']]={'reply':plan.get('reply','')}
            if compose_cases:
                replies,compose_model=transport.call('Write final guest-facing WhatsApp replies, 1-3 natural sentences in EACH case language. Only use verified_result. Preserve exact data lines, item names, quantities and prices. Never claim failed staff delivery succeeded or pending completion/stock confirmed. No analysis, internal/backend terminology, greetings or invented facts. Return {"results":[{"id":"case ID","reply":"guest reply"}]}. Cases are independent.\n'+json.dumps(compose_cases,ensure_ascii=False),[c['id'] for c in compose_cases],'compose')
                outputs.update(replies or {})
            for chat,case in zip(group,cases):
                turn=chat.chat['turns'][turn_index]
                plan=(plans or {}).get(case['id'])
                reply=outputs.get(case['id'],{}).get('reply','')
                errors=errors_for(turn,plan,config)
                if plan and plan.get("qa_execution_error"):
                    errors.append("Malformed action arguments")
                if not reply:
                    errors.append('No actual model reply; provider/batch failure')
                if reply and not bot._ai_content_is_usable(reply,'QA'):
                    errors.append('Internal analysis or unusable guest reply')
                if re.search(r'\bdemo\b',reply,re.I):
                    errors.append('Demo wording in production')
                if turn.get('contains') and any(value not in reply for value in turn['contains']):
                    errors.append('Missing expected sender fact')
                if turn.get('scope') and plan and plan.get('operation_text') != turn['scope']:
                    errors.append('Wrong bill scope')
                if turn.get('photo') and plan and turn['photo'].casefold() not in str(plan.get('photo_target','')).casefold():
                    errors.append('Wrong photo target')
                if turn.get('prices') is False and re.search(r'₹\s*\d',reply):
                    errors.append('Unrequested price')
                source=sources.get(case['id'],'')
                if source and reply and not ai.faithful_numbers_and_links(source,reply):
                    errors.append('Backend numeric/item/URL facts changed or missing')
                result={'source':source,'id':case['id'],'run_id':run_id,'segment':chat.chat['segment'],'question':case['message'],'reply':reply,'passed':not errors,'errors':errors,'plan':plan,'model':model,'prior_history':copy.deepcopy(chat.history[-8:]),'pending_before':case['verified_session_state'],'execution':'isolated synthetic records; no WhatsApp/Sheets writes','mode':'batched production interpretation policy; independent review stage not executed'}
                rows.append(result)
                print('HOTEL QA ROW: '+json.dumps(result,ensure_ascii=False),flush=True)
                chat.remember(case['message'],reply or '[No model reply: provider failure]')
            if not plans:
                # Quota exhaustion is a blocker, not a licence to flood other APIs.
                print('HOTEL QA BLOCKED: '+json.dumps({'run_id':run_id,'completed':len(rows),'reason':'No provider batch available'}),flush=True)
                return rows
    print('HOTEL QA SUMMARY: '+json.dumps({'run_id':run_id,'total':len(rows),'passed':sum(r['passed'] for r in rows),'tokens':transport.usage}),flush=True)
    return rows


def start(bot,run_id):
    def worker():
        time.sleep(45)
        try:
            run(bot,run_id)
        except Exception as exc:
            print('HOTEL QA WORKER ERROR: '+type(exc).__name__,flush=True)
    threading.Thread(target=worker,daemon=True,name='isolated-hotel-conversation-qa').start()
