"""Rasterize one verified generated PDF page without exposing an active PDF document."""
import resource
import sys


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    try:
        resource.setrlimit(resource.RLIMIT_DATA,(512*1024*1024,512*1024*1024))
    except (ValueError,OSError):
        pass
    try:
        import pypdfium2 as pdfium
        data=sys.stdin.buffer.read(5*1024*1024+1)
        if len(data)>5*1024*1024: raise ValueError()
        document=pdfium.PdfDocument(data)
        number=int(sys.argv[1])-1
        if number<0 or number>=min(len(document),25): raise ValueError()
        page=document[number]
        if page.get_width()>3000 or page.get_height()>3000: raise ValueError()
        image=page.render(scale=min(1.5,900/page.get_width())).to_pil()
        image.save(sys.stdout.buffer,format='PNG')
        page.close();document.close()
    except Exception:
        raise SystemExit(1) from None
