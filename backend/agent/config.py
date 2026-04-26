import os
from dotenv import load_dotenv

load_dotenv()


# Three providers are supported, in this priority order:
#   1. GitHub Models  → OpenAI-compatible gateway at https://models.github.ai,
#      billed against a GitHub PAT. GPT-4.1 / 4.1-mini / 4.1-nano live here with
#      generous hackathon-friendly limits and full tool-calling.
#   2. Gemini         → Google's own API. Default gemini-3.1-flash-lite-preview.
#      Strong free tier but preview endpoints 503 under load.
#   3. Groq           → legacy path; kept so old .env files keep working.
_GITHUB_DEFAULT_MODEL = "openai/gpt-4.1-mini"
_GITHUB_BASE_URL = "https://models.github.ai/inference"
_GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
_GROQ_DEFAULT_MODEL = "qwen/qwen3-32b"


def _provider() -> str:
    """Resolve which LLM provider to use.

    Explicit ``LLM_PROVIDER`` wins. Otherwise prefer GitHub Models (highest
    throughput on a hackathon PAT), then Gemini, then Groq. Raises if no
    credential is found so the agent fails fast instead of booting with a
    broken client.
    """
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in {"github", "github_models", "gh"}:
        return "github"
    if explicit in {"gemini", "google", "google_genai"}:
        return "gemini"
    if explicit == "groq":
        return "groq"
    if os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT"):
        return "github"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    raise RuntimeError(
        "No LLM credentials found. Set GITHUB_TOKEN (preferred), "
        "GEMINI_API_KEY, or GROQ_API_KEY in .env. See .env.example."
    )


def get_llm():
    """Return a chat client the agent nodes can call ``.bind_tools`` /
    ``.with_structured_output`` on.

    Returning the raw client (not a RunnableRetry / RunnableWithFallbacks)
    is deliberate — the LangGraph nodes in ``Ai_Agent.nodes`` need those
    two methods, which the Runnable wrappers do not expose.
    """
    provider = _provider()

    if provider == "github":
        # GitHub Models speaks OpenAI's chat-completions protocol, so
        # ChatOpenAI works out of the box once we point ``base_url`` at
        # their inference gateway and use a GitHub PAT as the api_key.
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
        return ChatOpenAI(
            model=os.getenv("LLM_MODEL", _GITHUB_DEFAULT_MODEL),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("LLM_TOP_P", "0.8")),
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", _GITHUB_BASE_URL),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "4")),
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # langchain-google-genai reads GOOGLE_API_KEY by default; mirror
        # GEMINI_API_KEY onto it so either name works in .env.
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return ChatGoogleGenerativeAI(
            model=os.getenv("LLM_MODEL", _GEMINI_DEFAULT_MODEL),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("LLM_TOP_P", "0.8")),
            google_api_key=api_key,
            # Preview endpoints (e.g. gemini-3.1-flash-lite-preview) 503 under
            # load; a single agent run makes many LLM calls (ReAct loop +
            # synthesizer + guardrail), so we need enough per-call retry
            # budget that one unlucky 503 doesn't fail the whole graph.
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "10")),
        )

    from langchain_groq import ChatGroq

    model = os.getenv("LLM_MODEL", _GROQ_DEFAULT_MODEL)
    # ``reasoning_effort`` is a Groq-specific knob for Qwen non-thinking mode;
    # only pass it when we're actually on a Qwen model to avoid breaking other
    # Groq-hosted models.
    extra = {"reasoning_effort": "none"} if "qwen" in model.lower() else {}
    return ChatGroq(
        model=model,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        model_kwargs={"top_p": float(os.getenv("LLM_TOP_P", "0.8"))},
        api_key=os.getenv("GROQ_API_KEY"),
        **extra,
    )
