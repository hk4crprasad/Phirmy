"""Measured synthetic final-transcript → first audio; never a live-provider claim."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'services/control'),str(ROOT/'scripts')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations',type=int,default=20)
    parser.add_argument('--assert-target',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/voice-latency/synthetic.json')
    arguments = parser.parse_args()
    assert 3 <= arguments.iterations <= 100
    with tempfile.TemporaryDirectory(prefix='voice-latency-') as temporary:
        os.environ.update(APP_ENV='test',DATABASE_URL='sqlite:///'+str(Path(temporary)/'qa.db'),SUPABASE_DB_PASSWORD='',
            VOICE_PROVIDER='legacy',SARVAM_API_KEY='',
            DATA_DIR=str(Path(temporary)/'data'),APP_SECRET=secrets.token_urlsafe(48),REDIS_URL='',
            OBJECT_STORAGE_PROVIDER='local',AZURE_STORAGE_CONNECTION_STRING='',AZURE_STORAGE_ACCOUNT_URL='',
            OPENAI_API_KEY='',OPENAI_MODEL='gpt-5.6-luna',OPENAI_BASE_URL='https://api.openai.com/v1',
            OPENAI_API_STYLE='responses',OPENAI_TOKEN_PARAMETER='max_output_tokens',
            EMBEDDING_API_KEY='',VECTOR_ENDPOINT='',VECTOR_API_KEY='',FISH_API_KEY='',FISH_VOICE_ID='synthetic-voice',FISH_TTS_MODEL='s2.1-pro',
            DEEPGRAM_API_KEY='',PLIVO_AUTH_ID='',PLIVO_AUTH_TOKEN='',TWILIO_ACCOUNT_SID='',TWILIO_AUTH_TOKEN='',
            TWILIO_API_KEY='',TWILIO_API_SECRET='',LIVE_CALLS_ENABLED='false',PHONE_TRIALS_ENABLED='false',
            PHONE_NUMBER_PURCHASES_ENABLED='false',LIVE_PAYMENTS_ENABLED='false',PAID_ACTIVATION_ENABLED='false',
            RAZORPAY_KEY_ID='',RAZORPAY_KEY_SECRET='',RAZORPAY_TEST_KEY_ID='',RAZORPAY_TEST_KEY_SECRET='',
            RAZORPAY_LIVE_KEY_ID='',RAZORPAY_LIVE_KEY_SECRET='',RAZORPAY_WEBHOOK_SECRET='',SMTP_HOST='',WORKER_ENABLED='false',
            CIPHER_KEY_PROVIDER='local',CIPHER_KEYS_JSON='',CIPHER_ACTIVE_KEY_ID='app-v1',CIPHER_VAULT_URL='',
            TURNSTILE_SITE_KEY='',TURNSTILE_SECRET_KEY='',WIDGET_BOT_CHALLENGE_ENABLED='false',REQUIRE_EMAIL_VERIFICATION='false',
            BILLING_OPERATOR_EMAILS='',BILLING_OPERATOR_REFUNDS_ENABLED='false',BILLING_DEVELOPMENT_ALLOWANCES_ENABLED='true')
        from sqlalchemy import select
        from studio.db import now, session_scope
        from studio.domain import default_agent
        from studio.main import initialize_database
        from studio.media import VoiceSession
        from studio.models import Call, Membership, User, VoiceTimingRecord, Workspace
        from studio.voice_latency import percentile
        from voice_latency_fixture import SyntheticVoiceProviders
        initialize_database()
        with session_scope(write=True) as db:
            owner = User(name='Synthetic voice owner',email='synthetic-voice@example.test',password_hash='unused')
            db.add(owner)
            db.flush()
            workspace = Workspace(name='Synthetic voice benchmark',free_allowance_user_id=owner.id)
            db.add(workspace)
            db.flush()
            db.add(Membership(workspace_id=workspace.id,user_id=owner.id,role='owner'))
            call = Call(workspace_id=workspace.id,mode='live',transport='browser',state='connected',connected_at=now())
            db.add(call)
            db.flush()
            workspace_id, call_id = workspace.id, call.id
        class Transport:
            async def send_json(self, data):
                pass
            async def send_bytes(self, data):
                assert data[:4]==b'NTV1' and len(data)>32
        fixture = SyntheticVoiceProviders()
        async def run():
            config = default_agent()
            config['recording']['enabled'] = False
            session = VoiceSession(Transport(),workspace_id,call_id,config,'live',timing_source='synthetic')
            session.transcript_deltas=True
            with fixture.installed():
                try:
                    for index in range(arguments.iterations):
                        await session.user_text('Describe this synthetic scenario.',final_received_at=time.monotonic(),input_kind='stt_final')
                        await session.task
                finally:await session.close_providers()
            assert not fixture.active_model_streams and all(socket.closed for socket in fixture.sockets)
            assert all(client.closed for client in fixture.clients)
        asyncio.run(run())
        with session_scope() as db:
            rows = list(db.scalars(select(VoiceTimingRecord).where(VoiceTimingRecord.call_id==call_id)))
            samples = [row.durations_ms['final_transcript_to_first_audio_ms'] for row in rows if row.status=='completed']
            assert len(samples)==arguments.iterations and all(value is not None for value in samples)
            result = {'source':'synthetic','provider_requests':'fake SDK and MessagePack socket; actual media/admission/metering',
                'fixture_delays_seconds':fixture.delays,'samples':len(samples),
                'transcript_mode':'delta-v1',
                'model_http_clients_created':len(fixture.clients),'model_requests':fixture.model_requests,
                'fish_websockets_opened':len(fixture.sockets),
                'final_transcript_to_first_audio_p50_ms':percentile(samples,.5),
                'final_transcript_to_first_audio_p95_ms':percentile(samples,.95),
                'target_p50_ms':1500,'target_p95_ms':2500,
                'turns':[{'status':row.status,'stages_ms':row.marks_ms,'durations_ms':row.durations_ms} for row in rows],
                'cleanup':'all fake provider streams and HTTP clients closed','live_provider_latency_measured':False}
        result['target_met'] = result['final_transcript_to_first_audio_p50_ms']<=1500 and result['final_transcript_to_first_audio_p95_ms']<=2500
        arguments.output.parent.mkdir(parents=True,exist_ok=True)
        arguments.output.write_text(json.dumps(result,indent=2))
        print(json.dumps({key:value for key,value in result.items() if key!='turns'}))
        if arguments.assert_target and not result['target_met']:
            raise SystemExit('Synthetic voice latency exceeded its target')


if __name__ == '__main__':
    main()
