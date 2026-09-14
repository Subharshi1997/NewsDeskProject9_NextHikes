import os

# langchain_config raises at import time if GROQ_API_KEY is unset, so the
# module can't even be collected for testing without a live key unless we
# supply a placeholder here. Client construction doesn't hit the network,
# so this never needs to be real. (Previously this set the pre-migration
# OPENAI_API_KEY/NEWSAPI_KEY names, which did nothing useful once
# langchain_config switched to Groq/multi-provider -- tests only kept
# passing because the real .env happened to supply GROQ_API_KEY too.)
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
