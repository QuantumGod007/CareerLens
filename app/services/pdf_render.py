import json
import os
import signal
import subprocess
import sys
import time

from app.core.config import ROOT
from app.core.errors import DomainError
from app.schemas.studio import PDFChecks


def isolated(module, data, timeout, args=(), memory_mb=512):
    process=subprocess.Popen([sys.executable,'-m',module,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,cwd=ROOT,start_new_session=True)
    deadline=time.monotonic()+timeout
    pending=data
    try:
        while True:
            try:
                output,_=process.communicate(pending,timeout=.2)
                break
            except subprocess.TimeoutExpired:
                pending=None
                if time.monotonic()>deadline:
                    raise DomainError('PDF_PROCESSING_TIMEOUT','PDF processing exceeded its time limit.',422)
                try:
                    rows=subprocess.check_output(['ps','-axo','pid=,ppid=,rss='],timeout=2,text=True).splitlines()
                    values=[tuple(map(int,row.split())) for row in rows if len(row.split())==3]
                except (OSError,subprocess.SubprocessError,ValueError):
                    raise DomainError('PDF_RESOURCE_MONITOR_UNAVAILABLE','Safe PDF resource monitoring is unavailable.',422) from None
                descendants={process.pid}
                for _ in range(10):
                    descendants.update(pid for pid,parent,_ in values if parent in descendants)
                if sum(rss for pid,_,rss in values if pid in descendants)>memory_mb*1024:
                    raise DomainError('PDF_RESOURCE_LIMIT','PDF processing exceeded its memory budget.',422)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL)
        process.communicate()
        raise
    if process.returncode!=0 or len(output)>8*1024*1024:
        raise DomainError('PDF_PROCESSING_FAILED','PDF processing failed safely.',422)
    return output


def render_resume(facts,draft):
    payload=json.dumps({'facts':facts,'tailored':draft.model_dump(mode='json')}).encode()
    if len(payload)>500000:
        raise DomainError('PDF_TEXT_LIMIT','The resume is too large for bounded rendering.',422)
    output=isolated('app.tools.render_resume',payload,45,memory_mb=1024)
    try:
        metadata,pdf=output.split(b'\n',1)
        metadata=json.loads(metadata)
        if metadata.get('error'):
            raise DomainError(metadata['error'],'Generated PDF validation failed; no document was published.',422)
        checks=PDFChecks.model_validate(metadata['checks'])
        if not pdf.startswith(b'%PDF-'):
            raise ValueError()
    except (ValueError,KeyError):
        raise DomainError('PDF_RENDER_FAILED','The generated PDF could not be verified.',422) from None
    return pdf,checks.model_dump()


def preview(pdf,page):
    output=isolated('app.tools.pdf_preview',pdf,15,args=(str(page),))
    if not output.startswith(b'\x89PNG\r\n\x1a\n'):
        raise DomainError('PDF_PREVIEW_FAILED','The private preview could not be rendered.',422)
    return output
