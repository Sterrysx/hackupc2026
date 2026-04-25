import os
from dotenv import load_dotenv

load_dotenv()


def get_llm():
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
        api_key=os.getenv("GROQ_API_KEY"),
    )
