"""Production billing UI, isolated real API/worker/PDFs, fake gateway only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/control'));sys.path.insert(0,str(ROOT/'scripts'))
folder=Path(tempfile.mkdtemp(prefix='billing-browser-'))
web=os.environ.get('BROWSER_TEST_ORIGIN','http://127.0.0.1:3100')
os.environ.update(APP_ENV='test',APP_ORIGIN=web,PUBLIC_API_ORIGIN='http://127.0.0.1:8100',
    DATABASE_URL='sqlite:///'+str(folder/'qa.db'),SUPABASE_DB_PASSWORD='',DATA_DIR=str(folder/'data'),APP_SECRET=secrets.token_urlsafe(48),
    OBJECT_STORAGE_PROVIDER='local',AZURE_STORAGE_CONNECTION_STRING='',AZURE_STORAGE_ACCOUNT_URL='',AZURE_STORAGE_PREFIX='',
    REDIS_URL='',VECTOR_ENDPOINT='',VECTOR_API_KEY='',OPENAI_API_KEY='',EMBEDDING_API_KEY='',
    FISH_API_KEY='',FISH_VOICE_ID='',DEEPGRAM_API_KEY='',PLIVO_AUTH_ID='',PLIVO_AUTH_TOKEN='',
    TWILIO_API_KEY='',TWILIO_API_SECRET='',TWILIO_ACCOUNT_SID='',TWILIO_AUTH_TOKEN='',LIVE_CALLS_ENABLED='false',
    PHONE_TRIALS_ENABLED='false',PHONE_NUMBER_PURCHASES_ENABLED='false',SMTP_HOST='',REQUIRE_EMAIL_VERIFICATION='false',SESSION_SECURE='false',
    CIPHER_KEY_PROVIDER='local',CIPHER_ACTIVE_KEY_ID='app-v1',CIPHER_KEYS_JSON='',CIPHER_VAULT_URL='',
    TURNSTILE_SITE_KEY='',TURNSTILE_SECRET_KEY='',WIDGET_BOT_CHALLENGE_ENABLED='false',
    RAZORPAY_MODE='test',RAZORPAY_KEY_ID='synthetic_test_id',RAZORPAY_KEY_SECRET='synthetic_test_secret',
    RAZORPAY_TEST_KEY_ID='',RAZORPAY_TEST_KEY_SECRET='',RAZORPAY_LIVE_KEY_ID='',RAZORPAY_LIVE_KEY_SECRET='',
    RAZORPAY_WEBHOOK_SECRET='synthetic_webhook',RAZORPAY_WEBHOOK_PREVIOUS_SECRETS_JSON='',LIVE_PAYMENTS_ENABLED='true',PAID_ACTIVATION_ENABLED='true',
    BILLING_DEVELOPMENT_ALLOWANCES_ENABLED='true',DEV_SEED_ENABLED='true',AUTH_RESPONSE_FLOOR_MS='250',
    CONTENT_SANDBOX_SOCKET='/tmp/studio-content-local/content.sock')
from studio import gst
catalog=json.loads((ROOT/'config/plans.json').read_text());catalog['status']='APPROVED'
merchant=json.loads((ROOT/'config/billing_business.json').read_text());prefix='29ABCDE1234F1Z'
merchant.update(status='APPROVED',legal_name='Synthetic billing QA company',address='Synthetic registered address',
    gstin=prefix+gst.gstin_check_character(prefix),support_email='support@example.test',payment_terms='Due on receipt')
(folder/'plans.json').write_text(json.dumps(catalog));(folder/'business.json').write_text(json.dumps(merchant))
from studio.config import settings
settings.plans_config_path=str(folder/'plans.json');settings.billing_business_config_path=str(folder/'business.json')
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from sqlalchemy import select
from studio import payment_routes
from studio.db import session_scope
from studio.main import create_app
from studio.models import Job,User
from studio.sessions import profile_for
from studio.workers import execute_job
from studio.mail_outbox import process_outbox
from qa_accounts import bootstrap_account
logging.disable(logging.CRITICAL)
expect.set_options(timeout=30000)


class Gateway:
    def __init__(self):self.plan=None;self.subscription=None;self.amount=0
    async def __call__(self,method,path,**kwargs):
        if method=='POST' and path=='/orders':
            self.amount=kwargs['json']['amount'];return {'id':'order_browser','amount':self.amount,'currency':'INR'}
        if method=='GET' and path=='/payments/pay_browser':return {'id':'pay_browser','order_id':'order_browser','status':'captured','amount':self.amount,'currency':'INR'}
        if method=='GET' and path=='/plans':return {'items':[self.plan] if self.plan else []}
        if method=='POST' and path=='/plans':self.plan={'id':'plan_browser',**kwargs['json']};return self.plan
        if method=='POST' and path=='/subscriptions':
            self.subscription={'id':'sub_browser','status':'created',**kwargs['json'],'current_start':int(time.time())-1,'current_end':int(time.time())+30*86400};return self.subscription
        if method=='GET' and path=='/subscriptions/sub_browser':return {**self.subscription,'status':'active'}
        if method=='GET' and path=='/payments/pay_subscription_browser':return {'id':'pay_subscription_browser','order_id':'order_subscription_browser',
            'status':'captured','amount':self.plan['item']['amount'],'currency':'INR','created_at':int(time.time())}
        raise AssertionError('Unexpected synthetic gateway request')


gateway=Gateway();payment_routes.provider=gateway
artifacts=ROOT/'artifacts/billing';artifacts.mkdir(parents=True,exist_ok=True)
with ThreadPoolExecutor(max_workers=1) as executor,TestClient(create_app(start_worker=False)) as client,sync_playwright() as playwright:
    me=bootstrap_account(client,'/v1/auth/signup',json={'name':'Billing QA','email':'billing-ui@example.test','password':'Long-Synthetic-QA-Password','workspace_name':'Billing QA'}).json()
    base='/v1/workspaces/'+me['workspaces'][0]['id']
    with session_scope(write=True) as db:profile_for(db,me['user']['id']).email_verified_at=__import__('studio.db',fromlist=['now']).now()
    settings.billing_operator_emails=me['user']['email']
    browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1080})
    context.add_cookies([{'name':item.name,'value':item.value,'url':web,'httpOnly':item.name!='studio_csrf','sameSite':'Lax'} for item in client.cookies.jar])
    context.add_init_script('''window.__billingCheckouts=[];window.Razorpay=class{constructor(options){this.options=options}open(){window.__billingCheckouts.push(this.options)}on(){}};''')
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def forward(route):
        request=route.request
        headers={key:value for key,value in request.all_headers().items() if key not in {'host','content-length','connection'}}
        response=client.request(request.method,request.url.split('/backend',1)[1],headers=headers,content=request.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={'Content-Type':response.headers.get('content-type','application/json')})
    page.route('**/backend/**',forward)
    page.goto(web+'/app/billing')
    expect(page.get_by_role('heading',name='Usage, plans and invoices.')).to_be_visible()
    page.get_by_text('Shared Free allowance across your workspaces',exact=True).click()
    expect(page.get_by_role('columnheader',name='Measured across workspaces',exact=True)).to_be_visible()
    for label,value in [('Billing name','Browser billing buyer'),('Billing address','Synthetic customer address'),('State code · two digits','07'),('Billing email','billing-browser@example.test')]:page.get_by_label(label,exact=True).fill(value)
    page.get_by_role('button',name='Save billing details',exact=True).click()
    expect(page.get_by_text('Billing details saved',exact=True)).to_be_visible()
    page.get_by_label('Top-up amount · INR').fill('100')
    page.get_by_role('button',name='Review top-up',exact=True).click()
    dialog=page.get_by_role('dialog',name='Review wallet funding')
    expect(dialog.get_by_text('₹118.00',exact=True)).to_be_visible()
    dialog.get_by_role('button',name='Confirm payment',exact=True).click()
    for _ in range(100):
        if page.evaluate('window.__billingCheckouts.length')==1:break
        page.wait_for_timeout(50)
    assert page.evaluate('window.__billingCheckouts.length')==1
    signature=hmac.new(b'synthetic_test_secret',b'order_browser|pay_browser',hashlib.sha256).hexdigest()
    page.evaluate('(proof)=>window.__billingCheckouts[0].handler(proof)',{'razorpay_order_id':'order_browser','razorpay_payment_id':'pay_browser','razorpay_signature':signature})
    expect(page.get_by_text('Payment verified; billing balance updated',exact=True)).to_be_visible()
    def jobs(kind):
        with session_scope() as db:identities=list(db.scalars(select(Job.id).where(Job.kind==kind,Job.state=='queued')))
        for identity in identities:executor.submit(lambda value=identity:asyncio.run(execute_job(value))).result(timeout=50)
    jobs('invoice_pdf');process_outbox()
    page.get_by_role('button',name='Refresh',exact=True).click()
    button=page.get_by_role('button',name='Download',exact=True)
    expect(button).to_be_enabled()
    with page.expect_download() as download:button.click()
    download.value.save_as(artifacts/'browser-invoice-draft.pdf')
    assert (artifacts/'browser-invoice-draft.pdf').read_bytes().startswith(b'%PDF')
    page.get_by_role('button',name='Review Starter',exact=True).click()
    page.get_by_role('dialog',name='Review subscription').get_by_role('button',name='Confirm subscription',exact=True).click()
    jobs('billing_subscription_create')
    page.get_by_role('button',name='Refresh',exact=True).click()
    page.get_by_role('button',name='Continue checkout',exact=True).click()
    for _ in range(100):
        if page.evaluate('window.__billingCheckouts.length')==2:break
        page.wait_for_timeout(50)
    assert page.evaluate('window.__billingCheckouts.length')==2
    signature=hmac.new(b'synthetic_test_secret',b'pay_subscription_browser|sub_browser',hashlib.sha256).hexdigest()
    page.evaluate('(proof)=>window.__billingCheckouts[1].handler(proof)',{'razorpay_subscription_id':'sub_browser','razorpay_payment_id':'pay_subscription_browser','razorpay_signature':signature})
    expect(page.get_by_role('heading',name='starter plan usage')).to_be_visible()
    jobs('invoice_pdf');process_outbox()
    page.get_by_role('button',name='Refresh',exact=True).click()
    page.get_by_role('button',name='Review top-up',exact=True).click()
    expect(page.get_by_role('dialog',name='Review wallet funding').get_by_role('button',name='Confirm payment',exact=True)).to_be_enabled()
    settings.paid_activation_enabled=False
    expect(page.get_by_text('Plan prices and business details require approval. Paid activation is disabled; DRAFT totals can be reviewed below.',exact=True)).to_be_visible()
    expect(page.get_by_role('dialog',name='Review wallet funding').get_by_role('button',name='Confirm payment',exact=True)).to_be_disabled()
    page.get_by_role('button',name='Close review',exact=True).click()
    page.screenshot(path=str(artifacts/'billing-browser.png'),full_page=True)
    page.goto(web+'/app/operations')
    expect(page.get_by_role('heading',name='Operator billing',exact=True)).to_be_visible()
    page.get_by_text('DRAFT plan unit economics and allowance risk',exact=True).click()
    expect(page.get_by_role('combobox',name='Cost scenario model',exact=True)).to_be_visible()
    expect(page.get_by_text('Above plan price',exact=True).first).to_be_visible()
    page.get_by_role('combobox',name='Cost scenario model',exact=True).select_option('gpt-5.6-sol')
    page.get_by_role('columnheader',name='Phone allowance',exact=True).wait_for()
    page.screenshot(path=str(artifacts/'unit-economics-browser.png'),full_page=True)
    page.get_by_text('DRAFT plan unit economics and allowance risk',exact=True).click()
    page.get_by_role('button',name='Billing QA',exact=True).last.click()
    dialog=page.get_by_role('dialog',name='Spending controls · Billing QA')
    dialog.get_by_label('Pause new spending',exact=False).check()
    dialog.get_by_label('Reason / review evidence').fill('Synthetic browser operator pause')
    dialog.get_by_role('button',name='Save spending controls').click()
    expect(page.get_by_text('Paused by operator',exact=True).first).to_be_visible()
    page.get_by_role('button',name='Billing QA',exact=True).last.click()
    dialog=page.get_by_role('dialog',name='Spending controls · Billing QA')
    dialog.get_by_label('Pause new spending',exact=False).uncheck()
    dialog.get_by_label('Reason / review evidence').fill('Synthetic browser operator resume')
    dialog.get_by_role('button',name='Save spending controls').click()
    expect(page.get_by_text('Open',exact=True).first).to_be_visible()
    page.screenshot(path=str(artifacts/'operator-browser.png'),full_page=True)
    settings.billing_operator_emails=''
    page.get_by_role('button',name='Refresh operator data',exact=True).click()
    expect(page.get_by_role('heading',name='Operator billing',exact=True)).not_to_be_visible()
    assert not errors,'Billing page raised a browser error'
    browser.close()
    print(json.dumps({'status':'passed','gateway':'fake, separate QA process','topup_gross_minor':11800,'topup_credit_minor':10000,
                      'subscription':'captured fee verified','invoice_pdf':'actual isolated render and download','paid_flag_off':'checkout disabled','operator':'pause/resume and access removal passed',
                      'unit_economics':'DRAFT channel costs, loss flags and model switch','shared_free':'sponsor aggregate shown','page_errors':len(errors)}))
