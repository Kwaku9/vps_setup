import os

LITELLM_BASE = os.environ.get("LITELLM_BASE_URL", "http://ai-stack-pod:4000/v1")
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
NOMIC_BASE = os.environ.get("NOMIC_BASE_URL", "http://nomic-embed:8090/v1")
GEN_MODEL = os.environ.get("GEN_MODEL", "claude-haiku-4-5")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "embeddinggemma")
NEO4J_URL = os.environ.get("NEO4J_URL", "http://neo4j-pod:7474")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
