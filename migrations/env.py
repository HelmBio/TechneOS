"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import get_settings
from core.models import Base

# Phase 4 models
from core.models.agent import AgentDefinition, AgenticRun, AgenticTask  # noqa: F401
from core.models.app import App, AppLaunch  # noqa: F401  app models
from core.models.artifact import ComputeArtifact  # noqa: F401
from core.models.bucket import ObjectStoreBucket  # noqa: F401
from core.models.compute_backend import ComputeBackend  # noqa: F401
from core.models.dataset import Dataset, DatasetVersion  # noqa: F401
from core.models.llm_provider import LLMProvider  # noqa: F401
from core.models.notification import Notification, Subscription  # noqa: F401
from core.models.pipeline import (  # noqa: F401
    Pipeline,
    PipelineRun,
    PipelineRunArtifact,
    PipelineStepRun,
)
from core.models.platform import PlatformSetting  # noqa: F401
from core.models.task_run import (  # noqa: F401
    TaskRun,
    TaskRunArtifact,
    TaskRunEvent,
)
from core.models.tool import HumanConfig, Tool, ToolVersion  # noqa: F401
from core.models.tool_run import ToolRun, ToolRunArtifact  # noqa: F401

# Import all models so Alembic can detect them
from core.models.user import ApiKey, AuditLog, Org, Role, Team, User  # noqa: F401

config = context.config

# Override sqlalchemy.url from settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
