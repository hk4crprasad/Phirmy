"""Credential-free Unix-socket broker. Each job gets a disposable process group."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import itertools

LIMIT=32_000_000
semaphore=asyncio.Semaphore(1)
identities=itertools.count(20000)


def cleanup(path):
    # Children have distinct UIDs. Reclaim ownership without following links.
    if not os.path.lexists(path):return
    os.chown(path,0,0,follow_symlinks=False)
    if os.path.islink(path):os.unlink(path);return
    os.chmod(path,0o700)
    if os.path.isdir(path):
        for entry in os.scandir(path):cleanup(entry.path)
        os.rmdir(path)
    else:os.unlink(path)


async def handle(reader,writer):
    process=None
    identity=None
    temporary=None
    tasks=[]
    locked=False
    try:
        async with asyncio.timeout(60):
            first=await reader.readline()
            if not first or len(first)>LIMIT:raise ValueError('Request limit exceeded')
            if json.loads(first).get('operation')=='health':
                writer.write(b'{"type":"result","ready":true}\n');await writer.drain();return
            await semaphore.acquire();locked=True
            folder=tempfile.mkdtemp(prefix='content-');temporary=folder
            identity=next(identities)
            if identity>=60000:raise ValueError('Recycle sandbox before UID exhaustion')
            # Popen changes cwd before dropping UID. Traversal is allowed;
            # inherited umask077 keeps all job-created files/dirs private.
            os.chmod(folder,0o711);os.chown(folder,identity,identity)
            process=await asyncio.create_subprocess_exec(sys.executable,'-I','/runtime/job.py',
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,limit=LIMIT+1,start_new_session=True,
                user=identity,group=identity,extra_groups=[],
                env={'PATH':'/app/.venv/bin:/usr/bin:/bin','HOME':folder,'TMPDIR':folder,
                     'LANG':'C.UTF-8','PYTHONUNBUFFERED':'1'},cwd=folder)
            process.stdin.write(first);await process.stdin.drain()
            async def to_client():
                while line:=await process.stdout.readline():
                    if len(line)>LIMIT:raise ValueError('Response limit exceeded')
                    writer.write(line);await writer.drain()
                    if json.loads(line).get('type') in {'result','error'}:return
            async def to_process():
                while line:=await reader.readline():
                    if len(line)>LIMIT:raise ValueError('Request limit exceeded')
                    process.stdin.write(line);await process.stdin.drain()
            tasks=[asyncio.create_task(to_client()),asyncio.create_task(to_process()),
                   asyncio.create_task(process.wait())]
            await asyncio.wait(tasks,timeout=40,return_when=asyncio.FIRST_COMPLETED)
            # stdout can still contain the final result when wait() completes.
            if process.returncode is not None:
                with contextlib.suppress(Exception):await asyncio.wait_for(tasks[0],1)
    except (Exception,asyncio.CancelledError) as error:
        print(json.dumps({'event':'sandbox.job_failed','type':type(error).__name__}),file=sys.stderr,flush=True)
        with contextlib.suppress(Exception):
            writer.write(b'{"type":"error","error":"Sandbox unavailable or timed out"}\n');await writer.drain()
    finally:
        if process is not None:
            with contextlib.suppress(ProcessLookupError):os.killpg(process.pid,signal.SIGKILL)
            # Chromium crash handlers or compromised children can create another
            # session. The job's never-reused UID is the final cancellation scope.
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    status=(entry/'status').read_text()
                    owner=next(line.split()[1] for line in status.splitlines() if line.startswith('Uid:'))
                    if int(owner)==identity:os.kill(int(entry.name),signal.SIGKILL)
                except (OSError,StopIteration):pass
            with contextlib.suppress(Exception):await process.wait()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if temporary is not None:
            with contextlib.suppress(OSError):cleanup(temporary)
        if locked:semaphore.release()
        writer.close()
        with contextlib.suppress(Exception):await writer.wait_closed()


async def main():
    os.umask(0o077)
    path=Path(os.environ.get('SANDBOX_SOCKET','/socket/content.sock'))
    client_group=int(os.environ.get('SANDBOX_CLIENT_GID','10001'))
    path.parent.mkdir(parents=True,exist_ok=True)
    os.chown(path.parent,0,client_group);os.chmod(path.parent,0o750)
    path.unlink(missing_ok=True)
    server=await asyncio.start_unix_server(handle,path=str(path),limit=LIMIT+1,backlog=8)
    os.chown(path,0,client_group);os.chmod(path,0o660)
    async with server:await server.serve_forever()


if __name__=='__main__':asyncio.run(main())
