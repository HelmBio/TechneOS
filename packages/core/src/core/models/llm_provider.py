"""LLM provider model — stores provider configurations for AI agents."""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401 — needed for relationship resolution


class LLMProvider(Base, UUIDMixin, TimestampMixin):
    """A registered LLM provider configuration.

    Each provider belongs to an organization. The API key is stored
    as a Fernet-encrypted value in the database (``encrypted_api_key``).
    """

    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="openai_compatible",
        comment="openai_compatible — covers OpenAI, Azure, Gemini, vLLM, Ollama, etc.",
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="API base URL; None = default OpenAI endpoint",
    )
    encrypted_api_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Fernet-encrypted API key stored at rest",
    )
    default_model: Mapped[str] = mapped_column(String(255), nullable=False)
    supported_models: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Default max tokens per request")

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Ownership — linked to an organization
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    org = relationship("Org", lazy="joined")
    creator = relationship("User", lazy="joined")
