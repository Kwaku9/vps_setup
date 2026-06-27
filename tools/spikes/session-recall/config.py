import os

LITELLM_BASE = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
NOMIC_BASE = os.environ.get("NOMIC_BASE_URL", "http://nomic-embed:8090/v1")
GEN_MODEL = os.environ.get("GEN_MODEL", "claude-haiku-4-5")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
