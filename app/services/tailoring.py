"""Conservative factual checks complement semantic verification; uncertain drafts never publish."""
import re
from uuid import UUID

from app.core.errors import DomainError
from app.schemas.ai import TailoredContent, VerificationResult, ClaimViolation
from app.services.matching import skills_in

CONTACT = {'name','email','phone','links'}
SECTION_ORDER = ['summary','skills','experience','projects','education','certifications','achievements','other']
VERB_ALIASES = {'built':'develop','developed':'develop','developing':'develop', 'implemented':'develop',
    'created':'create', 'creating':'create', 'used':'use', 'using':'with', 'utilized':'use',
    'tested':'test','testing':'test','tests':'test','designed':'design','designing':'design'}
FILLER = {'a','an','the'}
QUALIFIERS = {'no','not','never','without','basic','beginner','familiar','learning','assisted','supported',
              'academic','coursework','team','under','supervision','prototype','synthetic'}


def redact(text, name=None):
    if name:
        text = text.replace(name, '[identity omitted]')
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[contact omitted]', text)
    text = re.sub(r'https?://\S+|www\.\S+', '[link omitted]', text)
    text = re.sub(r'(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)', '[contact omitted]', text)
    return text


def ai_input(facts, structured):
    name = next((f['text'] for f in facts if f['kind']=='name'), None)
    values = [{'id':f['id'], 'section':f['kind'], 'text':redact(f['text'], name)} for f in facts if f['kind'] not in CONTACT]
    sections = [kind for kind in SECTION_ORDER if any(f['kind']==kind for f in facts)]
    jd = {'required_skills':[r.canonical_name for r in structured.required_skills],
          'preferred_skills':[r.canonical_name for r in structured.preferred_skills],
          'responsibilities':[redact(r.text) for r in structured.responsibilities],
          'eligibility':[redact(e.text) for e in structured.eligibility]}
    return {'facts':values, 'sections':sections, 'job_requirements':jd}


def tokens(text):
    values = re.findall(r"[\w+#]+(?:[.-][\w+#]+)*", text.casefold())
    return [VERB_ALIASES.get(t,t) for t in values if t not in FILLER]


def deterministic_violations(draft, facts):
    by_id = {f['id']:f for f in facts}
    issues, seen = [], set()
    sections = {f['kind'] for f in facts} - CONTACT
    if set(draft.selected_section_order) != sections or len(draft.selected_section_order) != len(sections):
        issues.append(ClaimViolation(item_id='section_order',reason='SECTION_ORDER_INVALID',source_fact_ids=[]))
    changes = {change.item_id:change for change in draft.changes}
    if len(changes) != len(draft.changes) or len(changes) != len(draft.claims):
        issues.append(ClaimViolation(item_id='changes',reason='CHANGE_TRACE_INVALID',source_fact_ids=[]))
    for claim in draft.claims:
        fact = by_id.get(claim.item_id)
        code = None
        if claim.item_id in seen:
            code = 'DUPLICATE_CLAIM'
        seen.add(claim.item_id)
        if not fact or [str(x) for x in claim.source_fact_ids] != [claim.item_id]:
            code = 'UNSUPPORTED_FACT_REFERENCE'
        elif claim.section != fact['kind'] or claim.section not in ('projects','experience'):
            code = 'ESSENTIAL_CLAIM_NOT_ALLOWED'
        else:
            before, after = fact['text'], claim.text
            old_tokens, new_tokens = tokens(before), tokens(after)
            if (len(after) > 4000 or not after.strip() or new_tokens != old_tokens
                    or re.findall(r'\d+(?:[.,]\d+)?%?', before) != re.findall(r'\d+(?:[.,]\d+)?%?', after)
                    or (set(before.casefold().split()) & QUALIFIERS) - set(after.casefold().split())
                    or set(skills_in(after)) != set(skills_in(before))
                    or (old_tokens and new_tokens and old_tokens[0] != new_tokens[0])):
                code = 'FACTUAL_EXPANSION_OR_PROTECTED_VALUE_CHANGE'
            change = changes.get(claim.item_id)
            if (not change or change.before != before or change.after != after or change.section != claim.section
                    or change.source_fact_ids != claim.source_fact_ids or not change.reason.strip()):
                code = 'CHANGE_TRACE_INVALID'
        if code:
            issues.append(ClaimViolation(item_id=claim.item_id,reason=code,source_fact_ids=claim.source_fact_ids))
    return issues


def restore_or_block(draft, facts, issues):
    by_id = {f['id']:f for f in facts}
    flagged = {issue.item_id for issue in issues}
    if any(identifier not in by_id for identifier in flagged):
        raise DomainError('VERIFICATION_FAILED', 'An unsupported essential claim or invalid trace blocks this document.', 422)
    claims, changes = [], []
    by_change = {change.item_id:change for change in draft.changes}
    for claim in draft.claims:
        if claim.item_id in flagged:
            fact = by_id[claim.item_id]
            if claim.section not in ('projects','experience') or claim.section != fact['kind']:
                raise DomainError('VERIFICATION_FAILED', 'An unsupported summary or essential statement blocks generation.', 422)
            claim = claim.model_copy(update={'text':fact['text'], 'source_fact_ids':[UUID(fact['id'])]})
            from app.schemas.ai import ChangeRecord
            change = ChangeRecord(section=fact['kind'],item_id=claim.item_id,before=fact['text'],after=fact['text'],
                reason='Original verified wording restored after the controlled repair failed verification.',source_fact_ids=claim.source_fact_ids)
        else:
            change = by_change[claim.item_id]
        claims.append(claim); changes.append(change)
    result = TailoredContent(claims=claims,changes=changes,selected_section_order=draft.selected_section_order)
    if deterministic_violations(result,facts):
        raise DomainError('VERIFICATION_FAILED', 'The final document remains unsupported.', 422)
    return result, sorted(flagged)


def semantic_issues(result: VerificationResult, draft):
    identifiers = {claim.item_id for claim in draft.claims}
    issues = result.violations + result.uncertain_claims
    if any(issue.item_id not in identifiers for issue in issues):
        raise DomainError('VERIFIER_RESPONSE_INVALID', 'The verifier referenced unknown content.', 422)
    if not result.passed and not issues:
        issues = [ClaimViolation(item_id=claim.item_id,reason='SEMANTIC_UNCERTAINTY',source_fact_ids=claim.source_fact_ids) for claim in draft.claims]
        if not issues:
            raise DomainError('VERIFICATION_FAILED', 'The verifier did not establish support.', 422)
    return issues
