"""Credential-free synthetic decoder diagnostic inside the production image."""
import subprocess

source = r'''
import io, os, resource, subprocess, wave
recording = io.BytesIO()
with wave.open(recording, 'wb') as output:
    output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
    output.writeframes(b'\0\0' * 3200)
resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
resource.setrlimit(resource.RLIMIT_STACK, (1024**2, 1024**2))
result = subprocess.run(['ffmpeg', '-v', 'error', '-cpucount', '1', '-threads', '1', '-filter_threads', '1',
    '-protocol_whitelist', 'pipe', '-i', 'pipe:0', '-vn', '-sn', '-dn', '-ac', '1',
    '-ar', '16000', '-threads', '1', '-f', 's16le', '-t', '31', 'pipe:1'],
    input=recording.getvalue(), capture_output=True, timeout=10,
    env={**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1', 'MALLOC_ARENA_MAX':'2'})
print('Synthetic FFmpeg check:', result.returncode, len(result.stdout), flush=True)
if result.returncode or len(result.stdout) != 6400:
    # Only the hardcoded generated recording reaches this diagnostic, never user audio.
    print(result.stderr.decode(errors='replace')[:3000], flush=True)
    raise SystemExit(1)
'''

subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                '--user', '20000:20000', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--memory', '1g',
                '--memory-swap', '1g', '--cpus', '1.5', '--pids-limit', '192',
                '--entrypoint', 'python', 'studio-content-sandbox:local', '-I', '-c', source], check=True)
