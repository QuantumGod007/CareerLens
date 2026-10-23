"""Render trusted escaped template, then measure text retention and page bounds."""
import io
import json
import resource
import sys
import unicodedata


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


def render(payload):
    import pdfplumber
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from playwright.sync_api import sync_playwright
    from app.core.config import ROOT
    from scripts.feasibility.common import browser_environment
    facts, draft = payload['facts'], payload['tailored']
    replacements = {claim['item_id']:claim['text'] for claim in draft['claims']}
    kinds = ('name','email','phone','links')
    name = next((f['text'] for f in facts if f['kind']=='name'), None)
    contacts = [f['text'] for f in facts if f['kind'] in kinds and not (f['kind']=='name' and f['text']==name)]
    sections = [{'label':kind.replace('_',' ').title(), 'items':[replacements.get(f['id'],f['text']) for f in facts if f['kind']==kind]}
                for kind in draft['selected_section_order']]
    environment = Environment(loader=FileSystemLoader(ROOT/'app'/'templates'), autoescape=True, undefined=StrictUndefined)
    html = environment.get_template('resume.html').render(name=name,contacts=contacts,sections=sections)
    browser_environment()
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            context = browser.new_context(java_script_enabled=False)
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(10000)
            page.set_content(html,wait_until='load')
            pdf = page.pdf(print_background=True,prefer_css_page_size=True)
            context.close()
    if len(pdf)>5*1024*1024:
        return {'error':'GENERATED_PDF_TOO_LARGE'},None
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        if not 1<=len(document.pages)<=25:
            return {'error':'GENERATED_PDF_PAGE_LIMIT'},None
        text = '\n'.join(page.extract_text() or '' for page in document.pages)
        compact = normalize(text)
        expected = [replacements.get(f['id'],f['text']) for f in facts]
        if any(normalize(value) not in compact for value in expected):
            return {'error':'PDF_ROUNDTRIP_MISMATCH'},None
        cursor=0
        for section in sections:
            index=compact.find(normalize(section['label'].upper()),cursor)
            if index<0: return {'error':'PDF_SECTION_ORDER_INVALID'},None
            cursor=index+len(normalize(section['label']))
        for page in document.pages:
            if any(c['x0'] < -1 or c['x1']>page.width+1 or c['top'] < -1 or c['bottom']>page.height+1 for c in page.chars):
                return {'error':'PDF_TEXT_OUT_OF_BOUNDS'},None
        return {'checks':{'extractable_text':'pass','contact_preservation':'pass','section_order':'pass',
            'no_unexpected_omissions':'pass','text_bounds':'pass','visual_layout':'not_assessed','pages':len(document.pages)}},pdf


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_CPU,(30,30))
    try:
        data=json.loads(sys.stdin.buffer.read(500001))
        result,pdf=render(data)
    except Exception:
        result,pdf={'error':'PDF_RENDER_FAILED'},None
    sys.stdout.buffer.write(json.dumps(result).encode()+b'\n'+(pdf or b''))
