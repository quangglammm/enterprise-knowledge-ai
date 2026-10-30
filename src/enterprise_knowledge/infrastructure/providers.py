"""Model provider adapters chosen from settings: shared by the API and the worker."""

import logging
from contextlib import AsyncExitStack

from pydantic import SecretStr

from enterprise_knowledge.config import Settings
from enterprise_knowledge.domain.ports import ChatModel, Embedder
from enterprise_knowledge.infrastructure.embeddings.hashing import HashingEmbedder
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder

logger = logging.getLogger(__name__)


def build_embedder(settings: Settings, stack: AsyncExitStack) -> Embedder:
    """The hashing embedder is dev-only; settings refuse it outside local and test."""
    api_key = settings.embedding_api_key
    if settings.embedding_provider == "hashing" or api_key is None:  # fpt requires a key
        return HashingEmbedder(dimension=settings.embedding_dimension)
    client = _fpt_client(
        settings.embedding_base_url,
        api_key,
        settings.embedding_request_timeout_seconds,
        settings,
        stack,
    )
    return FptEmbedder(
        client, model=settings.embedding_model, dimension=settings.embedding_dimension
    )


def build_chat_model(settings: Settings, stack: AsyncExitStack) -> ChatModel | None:
    api_key, model = settings.llm_api_key, settings.llm_model
    if api_key is None or model is None:  # Settings require both or neither
        logger.info("no chat model configured; /v1/answers is disabled")
        return None
    client = _fpt_client(
        settings.llm_base_url, api_key, settings.llm_request_timeout_seconds, settings, stack
    )
    return FptChatModel(client, model=model, json_mode=settings.llm_json_mode)


def _fpt_client(
    base_url: str,
    api_key: SecretStr,
    timeout_seconds: float,
    settings: Settings,
    stack: AsyncExitStack,
) -> FptClient:
    client = FptClient.create(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    stack.push_async_callback(client.aclose)
    return client
