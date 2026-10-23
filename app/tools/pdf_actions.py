"""Inspect PDF actions as data; never execute actions, scripts, files or links."""
import math
from urllib.parse import urlsplit

from pypdf.generic import (ArrayObject, DictionaryObject, IndirectObject, NullObject,
                           NameObject, TextStringObject, ByteStringObject, NumberObject, FloatObject)


class UnsupportedFeature(Exception):
    def __init__(self, code):
        self.code = code


def inspect_actions(reader):
    root = reader.trailer['/Root']
    page_refs = {(page.indirect_reference.idnum, page.indirect_reference.generation) for page in reader.pages}
    count = 0

    def fail(code):
        raise UnsupportedFeature(code)

    def resolve(value):
        seen = set()
        while isinstance(value, IndirectObject):
            reference = (value.idnum, value.generation)
            if reference in seen or len(seen) >= 32:
                fail('PDF_ACTION_LIMIT')
            seen.add(reference)
            value = value.get_object()
        return value

    def destination(value):
        value = resolve(value)
        if isinstance(value, (NameObject, TextStringObject, ByteStringObject)) and 0 < len(value) <= 1024:
            return  # A named local destination is data, not an action or a URL.
        if not isinstance(value, ArrayObject) or len(value) < 2:
            fail('PDF_INVALID_DESTINATION')
        page = value[0]
        if not isinstance(page, IndirectObject) or (page.idnum, page.generation) not in page_refs:
            fail('PDF_INVALID_DESTINATION')
        lengths = {'/XYZ':5, '/Fit':2, '/FitH':3, '/FitV':3, '/FitR':6, '/FitB':2, '/FitBH':3, '/FitBV':3}
        if not isinstance(value[1],NameObject) or lengths.get(value[1]) != len(value):
            fail('PDF_INVALID_DESTINATION')
        for coordinate in value[2:]:
            coordinate = resolve(coordinate)
            if isinstance(coordinate, NullObject) and value[1] != '/FitR':
                continue
            if not isinstance(coordinate, (NumberObject, FloatObject)) or not math.isfinite(float(coordinate)):
                fail('PDF_INVALID_DESTINATION')

    def action(value, *, link=False, ancestors=()):
        nonlocal count
        count += 1
        if count > 10000 or len(ancestors) > 64:
            fail('PDF_ACTION_LIMIT')
        value = resolve(value)
        if value is None or isinstance(value, NullObject):
            return
        if isinstance(value, (ArrayObject, NameObject, TextStringObject, ByteStringObject)):
            destination(value)
            return
        if not isinstance(value, DictionaryObject):
            fail('PDF_UNSUPPORTED_ACTION')
        if id(value) in ancestors:
            fail('PDF_ACTION_LIMIT')
        kind = resolve(value.get('/S'))
        if kind == '/JavaScript' or '/JS' in value:
            fail('PDF_JAVASCRIPT_ACTION')
        if kind == '/Launch':
            fail('PDF_LAUNCH_ACTION')
        if kind in ('/GoToR', '/GoToE'):
            fail('PDF_EXTERNAL_FILE_ACTION')
        if kind == '/GoTo':
            destination(value.get('/D'))
        elif kind == '/Named':
            if value.get('/N') not in ('/FirstPage', '/LastPage', '/NextPage', '/PrevPage'):
                fail('PDF_UNSUPPORTED_NAMED_ACTION')
        elif kind == '/URI':
            if not link:
                fail('PDF_AUTOMATIC_EXTERNAL_ACTION')
            uri = resolve(value.get('/URI'))
            if not isinstance(uri, TextStringObject) or urlsplit(str(uri)).scheme.lower() not in ('https', 'http', 'mailto', 'tel'):
                fail('PDF_UNSAFE_LINK_ACTION')
        else:
            fail('PDF_UNSUPPORTED_ACTION')
        if '/Next' in value:
            following = resolve(value['/Next'])
            chain = following if isinstance(following, ArrayObject) else [following]
            for item in chain:
                action(item, ancestors=(*ancestors, id(value)))

    def has_names(tree, ancestors=()):
        nonlocal count
        count += 1
        if count > 10000:fail('PDF_ACTION_LIMIT')
        tree = resolve(tree)
        if isinstance(tree, NullObject):
            return False
        if not isinstance(tree, DictionaryObject):
            fail('PDF_UNSUPPORTED_ACTION')
        if id(tree) in ancestors or len(ancestors) > 64:
            fail('PDF_ACTION_LIMIT')
        names, kids = resolve(tree.get('/Names', [])), resolve(tree.get('/Kids', []))
        if not isinstance(names, (list, ArrayObject)) or not isinstance(kids, (list, ArrayObject)):
            fail('PDF_UNSUPPORTED_ACTION')
        return bool(names) or any(has_names(kid, (*ancestors,id(tree))) for kid in kids)

    names = resolve(root.get('/Names', DictionaryObject()))
    if not isinstance(names, DictionaryObject):
        fail('PDF_UNSUPPORTED_ACTION')
    for key, code in (('/JavaScript','PDF_JAVASCRIPT_ACTION'), ('/EmbeddedFiles','PDF_EMBEDDED_FILES')):
        if key in names and has_names(names[key]):
            fail(code)
    if '/OpenAction' in root:
        action(root['/OpenAction'])

    seen, pending = set(), [(root,0)]
    events = {'/E','/X','/D','/U','/Fo','/Bl','/PO','/PC','/PV','/PI','/O','/C','/K','/F','/V','/WC','/WS','/DS','/WP','/DP'}
    while pending:
        value, depth = pending.pop()
        value = resolve(value)
        if not isinstance(value, (DictionaryObject, ArrayObject)) or id(value) in seen:
            continue
        seen.add(id(value));count += 1
        if count > 10000 or depth > 64:
            fail('PDF_ACTION_LIMIT')
        if isinstance(value, ArrayObject):
            pending.extend((item,depth+1) for item in value)
            continue
        subtype, kind = value.get('/Subtype'), value.get('/S')
        if kind == '/JavaScript' or '/JS' in value:
            fail('PDF_JAVASCRIPT_ACTION')
        if kind == '/Launch':
            fail('PDF_LAUNCH_ACTION')
        if kind in ('/GoToR','/GoToE'):
            fail('PDF_EXTERNAL_FILE_ACTION')
        if '/EF' in value or value.get('/Type') == '/EmbeddedFile' or subtype == '/FileAttachment' or value.get('/AF'):
            fail('PDF_EMBEDDED_FILES')
        if value.get('/XFA'):
            fail('PDF_XFA_CONTENT')
        if subtype in ('/RichMedia','/Screen','/Movie','/Sound','/3D'):
            fail('PDF_INTERACTIVE_MEDIA')
        annotation = value.get('/Type') == '/Annot' or subtype in ('/Link','/Widget')
        outline = '/Title' in value and '/Parent' in value
        if '/A' in value and (annotation or outline):
            action(value['/A'],link=subtype == '/Link')
        if '/AA' in value:
            additional = resolve(value['/AA'])
            owner = value is root or annotation or value.get('/Type') == '/Page' or '/FT' in value
            if owner or (isinstance(additional,DictionaryObject) and events.intersection(additional)):
                if not isinstance(additional,DictionaryObject):
                    fail('PDF_UNSUPPORTED_ACTION')
                for entry in additional.values():
                    action(entry)
        pending.extend((item,depth+1) for item in value.values())
