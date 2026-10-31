"""Explicit synthetic commercial approval; callers must fake every provider call."""
import json
from studio import gst,plans
from studio.config import settings


def enable_checkout(monkeypatch,tmp_path):
    catalog=plans.catalog();catalog.pop('content_hash',None);catalog['status']='APPROVED'
    catalog_path=tmp_path/'approved-synthetic-plans.json';catalog_path.write_text(json.dumps(catalog))
    merchant=gst.business();merchant.pop('content_hash',None)
    prefix='29ABCDE1234F1Z'
    merchant.update(status='APPROVED',legal_name='Synthetic invoice business',address='Synthetic registered address',
        gstin=prefix+gst.gstin_check_character(prefix),support_email='support@example.test',payment_terms='Due on receipt')
    business_path=tmp_path/'approved-synthetic-business.json';business_path.write_text(json.dumps(merchant))
    for name,value in {'plans_config_path':str(catalog_path),'billing_business_config_path':str(business_path),
        'paid_activation_enabled':True,'live_payments_enabled':True,'razorpay_mode':'test',
        'razorpay_key_id':'synthetic_test_id','razorpay_key_secret':'synthetic_test_secret',
        'razorpay_test_key_id':'','razorpay_test_key_secret':'','razorpay_webhook_secret':'synthetic-webhook-secret'}.items():
        monkeypatch.setattr(settings,name,value)
    return catalog_path,business_path


PROFILE={'legal_name':'Synthetic buyer','address':'Synthetic billing address','state_code':'07','gstin':'','email':'billing@example.test'}
