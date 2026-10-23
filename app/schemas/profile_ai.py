"""Fixed strict-output boundary; the server builds ProfileDraft from validated spans."""
from typing import Literal
from pydantic import Field
from app.schemas.api import StrictCommand
from app.schemas.ai import SourceSpan


class StructuredProfileFact(StrictCommand):
    kind: Literal['summary','skills','education','projects','experience','certifications','achievements','other']
    source_ref: SourceSpan


class GroqProfileDraft(StrictCommand):
    facts: list[StructuredProfileFact] = Field(min_length=1,max_length=80)
