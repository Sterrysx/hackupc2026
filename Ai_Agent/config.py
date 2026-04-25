import os
from dotenv import load_dotenv

load_dotenv()


def get_llm():
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("LLM_MODEL", "qwen/qwen3-32b"),
        # Qwen 3 recommended params for non-thinking instruct mode
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        model_kwargs={"top_p": float(os.getenv("LLM_TOP_P", "0.8"))},
        reasoning_effort="none",  # disable built-in CoT; the think tool handles scratchpad
        api_key=os.getenv("GROQ_API_KEY"),
    )
