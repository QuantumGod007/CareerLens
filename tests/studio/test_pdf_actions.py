import hashlib
import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject, TextStringObject,
                           NumberObject, NullObject)

from app.core.errors import DomainError
from app.services.profile_parser import extract_pdf
from .test_pipeline import resume_pdf, send, completed


def action_pdf(source, feature):
    writer=PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(source)))
    root=writer.root_object
    destination=ArrayObject([writer.pages[0].indirect_reference,NameObject('/Fit')])
    goto=DictionaryObject({NameObject('/S'):NameObject('/GoTo'),NameObject('/D'):destination})
    javascript=DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject('SYNTHETIC_PRIVATE_SCRIPT')})
    launch=DictionaryObject({NameObject('/S'):NameObject('/Launch'),NameObject('/F'):TextStringObject('SYNTHETIC_PRIVATE_FILE')})
    uri=DictionaryObject({NameObject('/S'):NameObject('/URI'),NameObject('/URI'):TextStringObject('https://example.invalid/resume')})
    annotation=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
        NameObject('/Rect'):ArrayObject([NumberObject(10),NumberObject(10),NumberObject(40),NumberObject(30)]),NameObject('/A'):uri})
    if feature=='open_destination':root[NameObject('/OpenAction')]=destination
    elif feature=='indirect_destination':root[NameObject('/OpenAction')]=writer._add_object(destination)
    elif feature=='goto':root[NameObject('/OpenAction')]=writer._add_object(goto)
    elif feature=='named_destination':
        root[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/GoTo'),NameObject('/D'):TextStringObject('synthetic-page')})
        root[NameObject('/Names')]=DictionaryObject({NameObject('/Dests'):DictionaryObject({NameObject('/Names'):ArrayObject([TextStringObject('synthetic-page'),destination])})})
    elif feature=='named_page':root[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/Named'),NameObject('/N'):NameObject('/NextPage')})
    elif feature in ('catalog_aa','page_aa'):
        (root if feature=='catalog_aa' else writer.pages[0])[NameObject('/AA')]=DictionaryObject({NameObject('/O'):goto})
    elif feature=='empty_trees':root[NameObject('/Names')]=DictionaryObject({NameObject('/JavaScript'):DictionaryObject({NameObject('/Names'):ArrayObject()}),NameObject('/EmbeddedFiles'):DictionaryObject()})
    elif feature in ('link','email_link','unsafe_link','annotation_js','annotation_launch','annotation_aa','chained_js','chained_external'):
        if feature=='email_link':uri[NameObject('/URI')]=TextStringObject('mailto:synthetic@example.invalid')
        if feature=='unsafe_link':uri[NameObject('/URI')]=TextStringObject('javascript:SYNTHETIC_PRIVATE_SCRIPT')
        if feature=='annotation_js':annotation[NameObject('/A')]=javascript
        if feature=='annotation_launch':annotation[NameObject('/A')]=launch
        if feature=='annotation_aa':annotation[NameObject('/AA')]=DictionaryObject({NameObject('/E'):javascript})
        if feature.startswith('chained'):
            annotation[NameObject('/A')]=goto
            goto[NameObject('/Next')]=ArrayObject([javascript if feature=='chained_js' else uri])
        writer.pages[0][NameObject('/Annots')]=ArrayObject([writer._add_object(annotation)])
    elif feature=='javascript':root[NameObject('/OpenAction')]=javascript
    elif feature=='page_js':writer.pages[0][NameObject('/AA')]=DictionaryObject({NameObject('/O'):javascript})
    elif feature=='named_js':root[NameObject('/Names')]=DictionaryObject({NameObject('/JavaScript'):DictionaryObject({NameObject('/Kids'):ArrayObject([writer._add_object(DictionaryObject({NameObject('/Names'):ArrayObject([TextStringObject('synthetic'),javascript])}))])})})
    elif feature=='launch':root[NameObject('/OpenAction')]=launch
    elif feature=='automatic_uri':root[NameObject('/OpenAction')]=uri
    elif feature=='external_file':root[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/GoToR'),NameObject('/F'):TextStringObject('private.pdf'),NameObject('/D'):destination})
    elif feature=='attachment':writer.add_attachment('synthetic.txt',b'SYNTHETIC_PRIVATE_ATTACHMENT')
    elif feature=='xfa':root[NameObject('/AcroForm')]=DictionaryObject({NameObject('/XFA'):TextStringObject('SYNTHETIC_PRIVATE_FORM')})
    elif feature=='viewer_print':root[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/Named'),NameObject('/N'):NameObject('/Print')})
    elif feature=='invalid_destination':root[NameObject('/OpenAction')]=ArrayObject([NumberObject(0),NameObject('/Fit')])
    elif feature=='cycle':
        reference=writer._add_object(goto);goto[NameObject('/Next')]=reference;root[NameObject('/OpenAction')]=reference
    elif feature=='tagged_attributes':root[NameObject('/StructTreeRoot')]=DictionaryObject({NameObject('/A'):DictionaryObject({NameObject('/O'):NameObject('/Layout')})})
    else:raise AssertionError(feature)
    result=io.BytesIO();writer.write(result);return result.getvalue()


@pytest.mark.parametrize('feature',['open_destination','indirect_destination','goto','named_destination','named_page',
                                   'catalog_aa','page_aa','empty_trees','link','email_link','tagged_attributes'])
def test_benign_navigation_and_contact_links_preserve_text_and_bytes(resume_pdf,feature):
    content=action_pdf(resume_pdf,feature)
    digest=hashlib.sha256(content).digest()
    pages=extract_pdf(content)
    assert any('Synthetic Candidate' in page['text'] for page in pages)
    assert hashlib.sha256(content).digest()==digest


@pytest.mark.parametrize('feature,code',[
    ('javascript','PDF_JAVASCRIPT_ACTION'),('page_js','PDF_JAVASCRIPT_ACTION'),('named_js','PDF_JAVASCRIPT_ACTION'),
    ('annotation_js','PDF_JAVASCRIPT_ACTION'),('annotation_aa','PDF_JAVASCRIPT_ACTION'),('chained_js','PDF_JAVASCRIPT_ACTION'),
    ('launch','PDF_LAUNCH_ACTION'),('annotation_launch','PDF_LAUNCH_ACTION'),
    ('automatic_uri','PDF_AUTOMATIC_EXTERNAL_ACTION'),('chained_external','PDF_AUTOMATIC_EXTERNAL_ACTION'),
    ('external_file','PDF_EXTERNAL_FILE_ACTION'),('unsafe_link','PDF_UNSAFE_LINK_ACTION'),
    ('attachment','PDF_EMBEDDED_FILES'),('xfa','PDF_XFA_CONTENT'),('viewer_print','PDF_UNSUPPORTED_NAMED_ACTION'),
    ('invalid_destination','PDF_INVALID_DESTINATION'),('cycle','PDF_ACTION_LIMIT'),
])
def test_executable_or_unsupported_features_fail_with_specific_private_safe_errors(resume_pdf,feature,code,caplog):
    with pytest.raises(DomainError) as error:extract_pdf(action_pdf(resume_pdf,feature))
    assert error.value.code==code and error.value.message
    assert 'SYNTHETIC_PRIVATE' not in error.value.message+caplog.text
    assert 'example.invalid' not in error.value.message+caplog.text


def test_upload_keeps_original_navigation_pdf_private_and_unmodified(client,headers,database,resume_pdf):
    content=action_pdf(resume_pdf,'open_destination')
    response=send(client,headers,'/api/v1/profiles',files={'resume':('synthetic.pdf',content,'application/pdf')})
    task=completed(client,headers,database,response.json())
    profile=client.get('/api/v1/profiles/'+task['result']['profile_version_id'],headers=headers).json()
    assert profile['confirmed_at'] is None and profile['parsing']['mode']=='local'
    assert client.get('/api/v1/artifacts/'+profile['source_artifact_id'],headers=headers).content==content
