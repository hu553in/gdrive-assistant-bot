from openai import OpenAI

from ..settings import settings


def make_llm_client() -> OpenAI | None:
    """Return an OpenAI client if LLM settings are configured."""

    if not settings.is_llm_enabled():
        return None
    return OpenAI(base_url=str(settings.LLM_BASE_URL), api_key=settings.LLM_API_KEY)
