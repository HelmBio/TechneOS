"""LLM provider model — stores provider configurations for AI agents."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401 — needed for relationship resolution


class LLMProvider(Base, UUIDMixin, TimestampMixin):
    """A registered LLM provider configuration.

    Each provider belongs to an organization. The API key is stored
    as a Fernet-encrypted value in the database (``encrypted_api_key``).
    """

    __tablename__ = "llm_providers"

    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    provider_type = Column(
        String(50),
        nullable=False,
        default="openai_compatible",
        comment="openai_compatible — covers OpenAI, Azure, Gemini, vLLM, Ollama, etc.",
    )
    base_url = Column(
        String(500),
        nullable=True,
        comment="API base URL; None = default OpenAI endpoint",
    )
    encrypted_api_key = Column(
        Text,
        nullable=True,
        comment="Fernet-encrypted API key stored at rest",
    )
    default_model = Column(String(255), nullable=False)
    supported_models = Column(JSONB, nullable=False, default=list)
    max_tokens = Column(Integer, nullable=True, comment="Default max tokens per request")

    is_default = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Ownership — linked to an organization
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    org = relationship("Org", lazy="joined")
    creator = relationship("User", lazy="joined")
