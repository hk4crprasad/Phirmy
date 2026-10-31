"""Start a hardened, credential-free local content sandbox; no application mounts.

The broker has only UID/GID/ownership capabilities; each job has a distinct
unprivileged UID and no capabilities. The application never receives a Docker
socket. Run `python scripts/content_sandbox.py start`.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import socket
import hashlib
from urllib.parse import urlsplit

IMAGE='studio-content-sandbox:local'


def fingerprint():
    digest=hashlib.sha256()
    for path in [Path('Dockerfile.sandbox'),Path('uv.lock'),Path('pyproject.toml'),*sorted(Path('sandbox_runtime').glob('*.py'))]:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build():
    command=['docker','build','-f','Dockerfile.sandbox','-t',IMAGE,'.']
    command[2:2]=['--label','studio.content.fingerprint='+fingerprint()]
    for name in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY']:
        if os.environ.get(name):command[2:2]=['--build-arg',name]
    # Some cloud Docker bridges cannot use the host's DNS. Pin only the configured
    # build proxy; TLS still verifies destination names and uv checks lock hashes.
    for name in ['HTTP_PROXY','HTTPS_PROXY']:
        proxy=urlsplit(os.environ.get(name,''))
        if proxy.hostname:
            address=socket.getaddrinfo(proxy.hostname,proxy.port or 80,type=socket.SOCK_STREAM)[0][4][0]
            command[2:2]=['--add-host',proxy.hostname+':'+address]
    if os.environ.get('STUDIO_SANDBOX_BUILD_NETWORK'):
        command[2:2]=['--network',os.environ['STUDIO_SANDBOX_BUILD_NETWORK']]
    certificate=os.environ.get('SSL_CERT_FILE')
    if certificate and Path(certificate).is_file():command[2:2]=['--secret','id=cloud_ca,src='+certificate]
    subprocess.run(command,check=True)


def ready(path):
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(2);probe.connect(str(path));probe.sendall(b'{"operation":"health"}\n')
            with probe.makefile('rb') as stream:return bool(json.loads(stream.readline(1024)).get('ready'))
    except (OSError,ValueError):return False


def start(folder,name):
    import fcntl
    lock=Path('/tmp')/('studio-content-start-'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        return _start(folder,name)


def _start(folder,name):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    try:folder.chmod(0o700)
    except PermissionError:pass  # The existing broker owns its socket directory.
    current=subprocess.run(['docker','image','inspect','--format','{{index .Config.Labels "studio.content.fingerprint"}}',IMAGE],
                           capture_output=True,text=True)
    if current.returncode or current.stdout.strip()!=fingerprint():
        build()
    existing=subprocess.run(['docker','inspect',name],capture_output=True,text=True)
    if existing.returncode==0:
        metadata=json.loads(existing.stdout)[0]
        owns=(metadata['Config']['Image']==IMAGE and metadata['HostConfig']['NetworkMode']=='none'
              and any(item.get('Source')==str(folder) and item.get('Destination')=='/socket' for item in metadata['Mounts'])
              and metadata['Config'].get('Labels',{}).get('studio.content.fingerprint'))
        if not owns:raise RuntimeError('Sandbox name belongs to another container; select a different name')
        if metadata['State']['Running'] and metadata['Config']['Labels']['studio.content.fingerprint']==fingerprint():
            if ready(folder/'content.sock'):return str(folder/'content.sock')
        subprocess.run(['docker','rm','-f',metadata['Id']],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','run','-d','--name',name,'--init','--network','none','--read-only',
        '--user','0:0','--cap-drop','ALL','--cap-add','SETUID','--cap-add','SETGID','--cap-add','CHOWN','--cap-add','KILL',
        '--env','SANDBOX_CLIENT_GID='+str(os.getgid()),'--security-opt','no-new-privileges',
        '--memory','1g','--memory-swap','1g','--cpus','1.5','--pids-limit','192','--shm-size','64m',
        '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777',
        '--mount','type=bind,src='+str(folder)+',dst=/socket',IMAGE],check=True,stdout=subprocess.DEVNULL)
    path=folder/'content.sock'
    for _ in range(200):
        if ready(path):return str(path)
        time.sleep(.05)
    raise RuntimeError('Content sandbox did not become ready')


def stop(name):
    found=subprocess.run(['docker','inspect',name],capture_output=True,text=True)
    if found.returncode:return
    metadata=json.loads(found.stdout)[0]
    mounts=[item['Source'] for item in metadata['Mounts'] if item.get('Destination')=='/socket']
    if metadata['Config']['Image']!=IMAGE or not metadata['Config'].get('Labels',{}).get('studio.content.fingerprint') or len(mounts)!=1:
        raise RuntimeError('Refusing to stop a container outside the content sandbox')
    subprocess.run(['docker','rm','-f',metadata['Id']],check=True,stdout=subprocess.DEVNULL)
    # The broker deliberately owns its socket directory while running. Restore
    # only that mount after shutdown so temporary environments can be cleaned.
    cleanup_code='import os,sys; p="/socket/content.sock"; os.path.lexists(p) and os.unlink(p); os.chmod("/socket",0o700); os.chown("/socket",int(sys.argv[1]),int(sys.argv[2]),follow_symlinks=False)'
    subprocess.run(['docker','run','--rm','--network','none','--read-only','--user','0:0',
        '--cap-drop','ALL','--cap-add','CHOWN','--security-opt','no-new-privileges','--pids-limit','16','--memory','64m',
        '--mount','type=bind,src='+mounts[0]+',dst=/socket','--entrypoint','python',IMAGE,'-I','-c',cleanup_code,str(os.getuid()),str(os.getgid())],check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['build','start','stop'])
    parser.add_argument('--name',default='studio-content-local')
    parser.add_argument('--directory',default='/tmp/studio-content-local')
    args=parser.parse_args()
    if args.action=='build':build()
    elif args.action=='start':print(json.dumps({'socket':start(args.directory,args.name)}))
    else:stop(args.name)
