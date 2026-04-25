import os
from dotenv import load_dotenv

load_dotenv()


def get_llm():
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        # Meta's recommended params for Llama 3.x instruct in agentic/tool-use contexts
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.6")),
        model_kwargs={"top_p": float(os.getenv("LLM_TOP_P", "0.9"))},
        reasoning_effort="none",  # disable built-in reasoning; the think tool handles scratchpad
        api_key=os.getenv("GROQ_API_KEY"),
    )
