"""Paid, cached Fish narration using root .env privately; never runs in CI."""
import hashlib, json, math, re, subprocess, sys
from pathlib import Path
import httpx
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / 'MainPage'

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout

def main():
    config = dotenv_values(ROOT / '.env')
    key, voice, model = (config.get(k) for k in ('FISH_API_KEY', 'FISH_VOICE_ID', 'FISH_TTS_MODEL'))
    if not all((key, voice, model)):
        raise RuntimeError('Missing configured Fish settings')
    scripts = json.loads((PAGE / 'src/motion/narration.json').read_text())
    directed = json.loads((PAGE / 'src/motion/narration-directed.json').read_text())
    if model != 'drama-3':
        raise RuntimeError('Directed narration requires configured drama-3')
    cache = ROOT / 'artifacts/mainpage/narration'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with httpx.Client(timeout=180) as client:
        for scenario, lines in scripts.items():
            clips = []
            frame = 0
            for i, line in enumerate(lines):
                performance = directed[scenario][i]
                plain = re.sub(r'\[[^]]*\]|<[^>]*>', '', performance)
                if ' '.join(plain.split()) != line:
                    raise RuntimeError('Performance and captions differ')
                stamp = hashlib.sha256((model + voice + performance).encode()).hexdigest()
                raw = cache / (stamp + '.mp3')
                if not raw.exists():
                    response = client.post('https://api.fish.audio/v1/tts', headers={'Authorization': 'Bearer ' + key, 'model': model}, json={'text':performance, 'reference_id':voice, 'format':'mp3', 'mp3_bitrate':192, 'latency':'normal', 'prosody':{'speed':1, 'volume':0}})
                    response.raise_for_status()
                    raw.write_bytes(response.content)
                target = PAGE / f'public/audio/{scenario}-{i}-{stamp[:10]}.mp3'
                run('ffmpeg','-y','-v','error','-i',str(raw),'-af','loudnorm=I=-16:TP=-1.5:LRA=7','-ar','44100','-c:a','libmp3lame','-b:a','192k',str(target))
                duration = float(run('ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(target)))
                run('ffmpeg','-v','error','-i',str(target),'-f','null','-')
                length = max(180, math.ceil((duration + .4) * 30))
                clips.append({'src':str(target.relative_to(PAGE / 'public')), 'text':line, 'from':frame, 'duration':length, 'audioSeconds':duration})
                frame += length
                print(f'{scenario} beat {i+1}: {duration:.2f}s', flush=True)
            manifest[scenario] = {'clips':clips, 'duration':frame}
    (PAGE / 'src/motion/narration-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Narration generation failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
