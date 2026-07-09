"""initial schema

The initial database schema for the TechneOS platform: all tables, enum types,
indexes, and constraints defined as a single baseline revision. Applied as raw
DDL so a fresh install provisions the complete schema in one step.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-09
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCHEMA_DDL = """
--
-- PostgreSQL database schema
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: agent_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agent_run_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: app_auth_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.app_auth_mode AS ENUM (
    'none',
    'oidc',
    'signed_jwt'
);


--
-- Name: app_launch_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.app_launch_mode AS ENUM (
    'external',
    'embedded'
);


--
-- Name: app_runtime_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.app_runtime_status AS ENUM (
    'pending',
    'building',
    'deploying',
    'active',
    'failed',
    'stopped'
);


--
-- Name: app_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.app_status AS ENUM (
    'draft',
    'active',
    'deprecated'
);


--
-- Name: artifact_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.artifact_kind AS ENUM (
    'wheel',
    'docker_image'
);


--
-- Name: artifact_origin; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.artifact_origin AS ENUM (
    'catalog',
    'platform',
    'other'
);


--
-- Name: artifact_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.artifact_status AS ENUM (
    'available',
    'deprecated',
    'deleted'
);


--
-- Name: compute_backend_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.compute_backend_status AS ENUM (
    'enabled',
    'disabled',
    'provisioning'
);


--
-- Name: dataset_version_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.dataset_version_status AS ENUM (
    'uploading',
    'processing',
    'ready',
    'failed'
);


--
-- Name: pipeline_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.pipeline_run_status AS ENUM (
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: pipeline_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.pipeline_type AS ENUM (
    'compute',
    'interactive',
    'hybrid'
);


--
-- Name: pipeline_version_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.pipeline_version_status AS ENUM (
    'draft',
    'testing',
    'active',
    'deprecated'
);


--
-- Name: step_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.step_run_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed',
    'skipped',
    'retrying',
    'cancelled'
);


--
-- Name: task_run_actor_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.task_run_actor_type AS ENUM (
    'user',
    'system',
    'pipeline'
);


--
-- Name: task_run_outcome; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.task_run_outcome AS ENUM (
    'completed',
    'declined',
    'cancelled',
    'expired'
);


--
-- Name: task_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.task_run_status AS ENUM (
    'pending',
    'accepted',
    'in_progress',
    'terminal'
);


--
-- Name: tool_run_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tool_run_status AS ENUM (
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: tool_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tool_type AS ENUM (
    'container',
    'module',
    'api',
    'pypi',
    'human'
);


--
-- Name: tool_version_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tool_version_status AS ENUM (
    'draft',
    'testing',
    'active',
    'deprecated'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    agent_id character varying(36),
    title character varying(500),
    summary text,
    metadata jsonb NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: COLUMN agent_runs.title; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.title IS 'optional conversation title';


--
-- Name: COLUMN agent_runs.summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_runs.summary IS 'auto-generated summary of conversation';


--
-- Name: agent_task_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_task_runs (
    agent_id character varying(36),
    status public.agent_run_status DEFAULT 'pending'::public.agent_run_status NOT NULL,
    task text NOT NULL,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    result jsonb,
    messages jsonb DEFAULT '[]'::jsonb NOT NULL,
    tool_calls jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_message text,
    tokens_used integer,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    org_id character varying(36) NOT NULL,
    submitted_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    conversation_id character varying(36)
);


--
-- Name: COLUMN agent_task_runs.task; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.task IS 'the user''s task or prompt';


--
-- Name: COLUMN agent_task_runs.context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.context IS 'input context (dataset refs, params, etc.)';


--
-- Name: COLUMN agent_task_runs.result; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.result IS 'structured result from the agent';


--
-- Name: COLUMN agent_task_runs.messages; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.messages IS 'conversation history / reasoning trace';


--
-- Name: COLUMN agent_task_runs.tool_calls; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.tool_calls IS 'log of tool invocations';


--
-- Name: COLUMN agent_task_runs.conversation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_task_runs.conversation_id IS 'links this run to a multi-turn conversation';


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    agent_type character varying(50) DEFAULT 'conversational'::character varying NOT NULL,
    framework character varying(50) DEFAULT 'custom'::character varying NOT NULL,
    system_prompt text,
    model_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    parameters_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_parameters jsonb DEFAULT '{}'::jsonb NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    is_public boolean DEFAULT false NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_platform boolean DEFAULT false NOT NULL,
    package_config jsonb,
    version_history jsonb NOT NULL
);


--
-- Name: COLUMN agents.agent_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.agent_type IS 'conversational | autonomous | reactive';


--
-- Name: COLUMN agents.framework; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.framework IS 'custom | langchain | autogen | crewai';


--
-- Name: COLUMN agents.is_platform; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.is_platform IS 'Platform-level agent (excluded from user agent listings)';


--
-- Name: COLUMN agents.package_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.package_config IS 'Wheel package coords for runtime install (name, version, index_url, entry_point)';


--
-- Name: COLUMN agents.version_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.version_history IS 'Append-only [{version, captured_at, ...definition snapshot}] log';


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    name character varying(255) NOT NULL,
    prefix character varying(10) NOT NULL,
    key_hash character varying(255) NOT NULL,
    user_id character varying(36) NOT NULL,
    scopes jsonb NOT NULL,
    is_active boolean NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: app_launches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_launches (
    id character varying(36) NOT NULL,
    app_id character varying(36) NOT NULL,
    org_id character varying(36) NOT NULL,
    launched_by character varying(36) NOT NULL,
    launch_mode character varying(20) NOT NULL,
    auth_mode character varying(20) NOT NULL,
    client_ip character varying(45),
    user_agent character varying(512),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: apps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.apps (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    icon_url character varying(512),
    thumbnail_url character varying(512),
    launch_mode public.app_launch_mode NOT NULL,
    external_url character varying(1024),
    docker_image character varying(512),
    docker_tag character varying(128) DEFAULT 'latest'::character varying,
    container_port integer,
    env jsonb DEFAULT '{}'::jsonb NOT NULL,
    resource_requirements jsonb DEFAULT '{}'::jsonb NOT NULL,
    health_check_path character varying(255) DEFAULT '/'::character varying,
    embed_sandbox character varying(255),
    embed_allow character varying(255),
    runtime_status public.app_runtime_status DEFAULT 'pending'::public.app_runtime_status NOT NULL,
    runtime_endpoint character varying(512),
    last_deployed_at timestamp with time zone,
    last_build_error text,
    auth_mode public.app_auth_mode DEFAULT 'none'::public.app_auth_mode NOT NULL,
    oidc_client_id character varying(255),
    launch_token_audience character varying(255),
    launch_token_ttl_seconds integer DEFAULT 300,
    status public.app_status DEFAULT 'draft'::public.app_status NOT NULL,
    is_public boolean DEFAULT false NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    updated_by character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: COLUMN apps.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.apps.category IS 'visualization | notebook | editor | data-browser | ml-playground | general';


--
-- Name: COLUMN apps.runtime_endpoint; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.apps.runtime_endpoint IS 'internal host:port the gateway proxies to';


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id character varying(36) NOT NULL,
    user_id character varying(36),
    action character varying(50) NOT NULL,
    resource_type character varying(50) NOT NULL,
    resource_id character varying(36),
    details jsonb NOT NULL,
    ip_address character varying(45),
    user_agent character varying(500),
    "timestamp" timestamp with time zone NOT NULL
);


--
-- Name: compute_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compute_artifacts (
    id character varying(36) NOT NULL,
    kind public.artifact_kind NOT NULL,
    origin public.artifact_origin DEFAULT 'other'::public.artifact_origin NOT NULL,
    name character varying(512) NOT NULL,
    version character varying(256) NOT NULL,
    registry_url character varying(512),
    digest character varying(256),
    size_bytes bigint,
    source_commit_sha character varying(64),
    source_repo character varying(255),
    status public.artifact_status DEFAULT 'available'::public.artifact_status NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    published_at timestamp with time zone,
    published_by character varying(36),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: compute_backends; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compute_backends (
    id character varying(36) NOT NULL,
    name character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    backend_type character varying(50) NOT NULL,
    description text,
    status public.compute_backend_status DEFAULT 'disabled'::public.compute_backend_status NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dataset_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset_versions (
    dataset_id character varying(36) NOT NULL,
    version integer NOT NULL,
    description text,
    storage_bucket character varying(255) NOT NULL,
    status public.dataset_version_status NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    files jsonb DEFAULT '[]'::jsonb NOT NULL,
    updated_by character varying(36),
    transfer_method character varying(50),
    source_bucket_id character varying(36),
    source_files jsonb
);


--
-- Name: COLUMN dataset_versions.transfer_method; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dataset_versions.transfer_method IS 'How files were added: ''upload'' or ''transfer''';


--
-- Name: COLUMN dataset_versions.source_files; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dataset_versions.source_files IS 'Original file paths/keys in the source bucket';


--
-- Name: datasets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.datasets (
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    data_type character varying(50) NOT NULL,
    tags jsonb NOT NULL,
    metadata jsonb NOT NULL,
    is_public boolean NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_format character varying(50),
    updated_by character varying(36),
    data_schema jsonb
);


--
-- Name: COLUMN datasets.data_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.data_type IS 'tabular | molecular | sequence | image | other';


--
-- Name: COLUMN datasets.data_schema; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.data_schema IS 'JSON Schema (draft) describing the expected structure of data files';


--
-- Name: llm_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_providers (
    id character varying(36) NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    provider_type character varying(50) DEFAULT 'openai_compatible'::character varying NOT NULL,
    base_url character varying(500),
    default_model character varying(255) NOT NULL,
    supported_models jsonb DEFAULT '[]'::jsonb NOT NULL,
    max_tokens integer,
    is_default boolean DEFAULT false NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    encrypted_api_key text
);


--
-- Name: COLUMN llm_providers.encrypted_api_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.llm_providers.encrypted_api_key IS 'Fernet-encrypted API key stored at rest; takes precedence over api_key_env';


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    message text NOT NULL,
    link character varying(512),
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    source_type character varying(50),
    source_id character varying(36),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: COLUMN notifications.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.notifications.category IS 'tool_update | pipeline_status | dataset_update | system | general';


--
-- Name: object_store_buckets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_store_buckets (
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    bucket_name character varying(255) NOT NULL,
    endpoint_url character varying(500),
    region character varying(100),
    secure boolean NOT NULL,
    encrypted_access_key text,
    encrypted_secret_key text,
    is_default boolean NOT NULL,
    is_active boolean NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL
);


--
-- Name: COLUMN object_store_buckets.endpoint_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.object_store_buckets.endpoint_url IS 'S3-compatible endpoint URL; None = use platform default';


--
-- Name: COLUMN object_store_buckets.region; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.object_store_buckets.region IS 'AWS region or equivalent';


--
-- Name: COLUMN object_store_buckets.secure; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.object_store_buckets.secure IS 'Use TLS (HTTPS)';


--
-- Name: COLUMN object_store_buckets.encrypted_access_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.object_store_buckets.encrypted_access_key IS 'Fernet-encrypted access key stored at rest';


--
-- Name: COLUMN object_store_buckets.encrypted_secret_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.object_store_buckets.encrypted_secret_key IS 'Fernet-encrypted secret key stored at rest';


--
-- Name: orgs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orgs (
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    description text,
    settings jsonb NOT NULL,
    is_active boolean NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: pipeline_run_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_run_artifacts (
    run_id character varying(36) NOT NULL,
    step_name character varying(255),
    name character varying(255) NOT NULL,
    artifact_type character varying(50) NOT NULL,
    storage_bucket character varying(255) NOT NULL,
    storage_key character varying(1024) NOT NULL,
    file_name character varying(255) NOT NULL,
    file_size integer NOT NULL,
    content_type character varying(100) NOT NULL,
    checksum_sha256 character varying(64),
    metadata jsonb NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    io_type character varying(20) NOT NULL
);


--
-- Name: COLUMN pipeline_run_artifacts.step_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipeline_run_artifacts.step_name IS 'null if pipeline-level artifact';


--
-- Name: COLUMN pipeline_run_artifacts.artifact_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipeline_run_artifacts.artifact_type IS 'file | table | plot | model | report';


--
-- Name: COLUMN pipeline_run_artifacts.io_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipeline_run_artifacts.io_type IS '''input'' or ''output''';


--
-- Name: pipeline_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_runs (
    status public.pipeline_run_status NOT NULL,
    parameters jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    airflow_dag_id character varying(255),
    airflow_run_id character varying(255),
    org_id character varying(36) NOT NULL,
    submitted_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    restarted_from character varying(36),
    name character varying(255),
    version_id character varying(36) NOT NULL
);


--
-- Name: pipeline_step_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_step_runs (
    run_id character varying(36) NOT NULL,
    step_name character varying(255) NOT NULL,
    tool_version_id character varying(36),
    status public.step_run_status NOT NULL,
    parameters jsonb NOT NULL,
    outputs jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: pipeline_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_versions (
    id character varying(36) NOT NULL,
    pipeline_id character varying(36) NOT NULL,
    version integer NOT NULL,
    status public.pipeline_version_status DEFAULT 'draft'::public.pipeline_version_status NOT NULL,
    changelog text,
    created_by character varying(36) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by character varying(36),
    bindings jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: pipelines; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipelines (
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    tags jsonb NOT NULL,
    is_public boolean NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    pipeline_type public.pipeline_type DEFAULT 'compute'::public.pipeline_type NOT NULL,
    readme text,
    updated_by character varying(36),
    steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    edges jsonb DEFAULT '[]'::jsonb NOT NULL,
    parameters_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    topology_hash character varying(64),
    forked_from character varying(36)
);


--
-- Name: COLUMN pipelines.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipelines.category IS 'docking | scoring | admet | ml | general | molecular-dynamics | quantum-chemistry | cheminformatics | bioinformatics | machine-learning | data-processing | other';


--
-- Name: COLUMN pipelines.pipeline_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipelines.pipeline_type IS 'compute | interactive | hybrid';


--
-- Name: COLUMN pipelines.readme; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pipelines.readme IS 'Pipeline documentation in Markdown';


--
-- Name: platform_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_settings (
    key character varying(128) NOT NULL,
    value jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id character varying(36) NOT NULL,
    name character varying(50) NOT NULL,
    description text,
    permissions jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subscriptions (
    id character varying(36) NOT NULL,
    user_id character varying(36) NOT NULL,
    resource_type character varying(50) NOT NULL,
    resource_id character varying(36) NOT NULL,
    preferences jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_run_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_run_artifacts (
    id character varying(36) NOT NULL,
    task_run_id character varying(36),
    org_id character varying(36) NOT NULL,
    action_type character varying(50) NOT NULL,
    event_id character varying(36),
    name character varying(255) NOT NULL,
    file_name character varying(255) NOT NULL,
    file_size bigint NOT NULL,
    content_type character varying(100) DEFAULT 'application/octet-stream'::character varying NOT NULL,
    checksum_sha256 character varying(64),
    storage_bucket character varying(255) NOT NULL,
    storage_key character varying(1024) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_by character varying(36) NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: task_run_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_run_events (
    id character varying(36) NOT NULL,
    task_run_id character varying(36) NOT NULL,
    action_type character varying(50) NOT NULL,
    actor_user_id character varying(36),
    actor_type public.task_run_actor_type NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    parent_event_id character varying(36),
    message text
);


--
-- Name: task_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_runs (
    id character varying(36) NOT NULL,
    org_id character varying(36) NOT NULL,
    tool_id character varying(36) NOT NULL,
    tool_slug character varying(255) NOT NULL,
    tool_version_id character varying(36) NOT NULL,
    pipeline_run_id character varying(36),
    pipeline_step_run_id character varying(36),
    step_name character varying(255),
    input_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status public.task_run_status DEFAULT 'pending'::public.task_run_status NOT NULL,
    outcome public.task_run_outcome,
    due_at timestamp with time zone,
    original_due_at timestamp with time zone,
    require_attachments boolean DEFAULT false NOT NULL,
    cfg_due_in_hours integer,
    assignment_type character varying(50) NOT NULL,
    started_by character varying(36) NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    output_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    finished_by character varying(36),
    finished_at timestamp with time zone,
    assigned_user_id character varying(36),
    assigned_team_slug character varying(255),
    project_lead_id character varying(36),
    accepted_at timestamp with time zone,
    tool_version_no integer,
    priority character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    CONSTRAINT ck_task_runs_outcome_iff_terminal CHECK ((((status = 'terminal'::public.task_run_status) AND (outcome IS NOT NULL)) OR ((status <> 'terminal'::public.task_run_status) AND (outcome IS NULL))))
);


--
-- Name: COLUMN task_runs.input_params; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_runs.input_params IS 'Frozen input parameters at creation time';


--
-- Name: COLUMN task_runs.outcome; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_runs.outcome IS 'Set only when status=''terminal''';


--
-- Name: COLUMN task_runs.output_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_runs.output_data IS 'Output payload submitted by the assignee (was task_run_submissions.output_data)';


--
-- Name: COLUMN task_runs.finished_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_runs.finished_by IS 'User who submitted the task (was task_run_submissions.submitted_by)';


--
-- Name: COLUMN task_runs.finished_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.task_runs.finished_at IS 'When the task was submitted (was task_run_submissions.submitted_at)';


--
-- Name: teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.teams (
    name character varying(255) NOT NULL,
    org_id character varying(36) NOT NULL,
    description text,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    slug character varying(255) NOT NULL
);


--
-- Name: COLUMN teams.slug; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.teams.slug IS 'URL-safe identifier, unique within an org';


--
-- Name: tool_docker_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_docker_configs (
    tool_version_id character varying(36) NOT NULL,
    docker_image character varying(512) NOT NULL,
    docker_tag character varying(128) DEFAULT 'latest'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    artifact_id character varying(36)
);


--
-- Name: tool_human_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_human_configs (
    tool_version_id character varying(36) NOT NULL,
    assignment_type character varying(50) DEFAULT 'team'::character varying NOT NULL,
    due_in_hours integer DEFAULT 72,
    require_attachments boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    default_user_email character varying(255),
    default_team_slug character varying(255),
    priority character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    default_project_lead_email character varying(255),
    CONSTRAINT ck_tool_human_configs_default_assignee_xor CHECK (((default_user_email IS NULL) OR (default_team_slug IS NULL)))
);


--
-- Name: COLUMN tool_human_configs.assignment_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_human_configs.assignment_type IS '''user'' for a specific user, ''team'' for a team';


--
-- Name: COLUMN tool_human_configs.due_in_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_human_configs.due_in_hours IS 'Default due time in hours from assignment creation';


--
-- Name: COLUMN tool_human_configs.require_attachments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_human_configs.require_attachments IS 'Whether submission requires file attachments';


--
-- Name: COLUMN tool_human_configs.default_user_email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_human_configs.default_user_email IS 'Default user assignee (mutually exclusive with default_team_slug)';


--
-- Name: COLUMN tool_human_configs.default_team_slug; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_human_configs.default_team_slug IS 'Default team assignee (mutually exclusive with default_user_id)';


--
-- Name: tool_pypi_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_pypi_configs (
    tool_version_id character varying(36) NOT NULL,
    package_name character varying(255) NOT NULL,
    package_version character varying(64) NOT NULL,
    entry_point character varying(255) NOT NULL,
    package_index_url character varying(512),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_tools jsonb,
    artifact_id character varying(36)
);


--
-- Name: COLUMN tool_pypi_configs.agent_tools; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_pypi_configs.agent_tools IS 'List of async function names contributed to the Platform Assistant agent, e.g. [''calculate_molecule_properties'']. Null means no agent-side tools.';


--
-- Name: tool_run_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_run_artifacts (
    id character varying(36) NOT NULL,
    tool_run_id character varying(36) NOT NULL,
    storage_bucket character varying(255) NOT NULL,
    storage_key character varying(1024) NOT NULL,
    file_name character varying(255) NOT NULL,
    file_size bigint NOT NULL,
    content_type character varying(100) NOT NULL,
    checksum_sha256 character varying(64),
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    io_type character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL
);


--
-- Name: tool_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_runs (
    id character varying(36) NOT NULL,
    tool_version_id character varying(36) NOT NULL,
    status public.tool_run_status NOT NULL,
    parameters jsonb NOT NULL,
    outputs jsonb NOT NULL,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    airflow_dag_id character varying(255),
    airflow_run_id character varying(255),
    org_id character varying(36) NOT NULL,
    submitted_by character varying(36) NOT NULL,
    restarted_from character varying(36),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    log_storage_key character varying(1024)
);


--
-- Name: tool_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_versions (
    tool_id character varying(36) NOT NULL,
    version integer NOT NULL,
    input_schema json NOT NULL,
    output_schema json NOT NULL,
    parameters_schema json NOT NULL,
    resource_requirements jsonb NOT NULL,
    status public.tool_version_status NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    updated_by character varying(36),
    changelog text
);


--
-- Name: COLUMN tool_versions.resource_requirements; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_versions.resource_requirements IS 'e.g. {"cpu": "2", "memory": "4Gi", "gpu": 1}';


--
-- Name: COLUMN tool_versions.changelog; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tool_versions.changelog IS 'Per-release notes — what changed in this version';


--
-- Name: tools; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tools (
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    description text,
    category character varying(50) NOT NULL,
    tags jsonb NOT NULL,
    is_public boolean NOT NULL,
    org_id character varying(36) NOT NULL,
    created_by character varying(36) NOT NULL,
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    tool_type public.tool_type DEFAULT 'container'::public.tool_type NOT NULL,
    updated_by character varying(36),
    readme text
);


--
-- Name: COLUMN tools.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.category IS 'docking | scoring | admet | ml | general';


--
-- Name: COLUMN tools.tool_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.tool_type IS 'container | library | api';


--
-- Name: COLUMN tools.readme; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tools.readme IS 'Tool documentation in Markdown (moved from tool_versions.readme)';


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    email character varying(255) NOT NULL,
    full_name character varying(255) NOT NULL,
    hashed_password character varying(255),
    is_active boolean NOT NULL,
    org_id character varying(36) NOT NULL,
    team_id character varying(36),
    role_id character varying(36),
    external_id character varying(255),
    id character varying(36) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: agent_task_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_task_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: app_launches app_launches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_launches
    ADD CONSTRAINT app_launches_pkey PRIMARY KEY (id);


--
-- Name: apps apps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apps
    ADD CONSTRAINT apps_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: compute_artifacts compute_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compute_artifacts
    ADD CONSTRAINT compute_artifacts_pkey PRIMARY KEY (id);


--
-- Name: compute_backends compute_backends_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compute_backends
    ADD CONSTRAINT compute_backends_name_key UNIQUE (name);


--
-- Name: compute_backends compute_backends_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compute_backends
    ADD CONSTRAINT compute_backends_pkey PRIMARY KEY (id);


--
-- Name: tool_docker_configs container_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_docker_configs
    ADD CONSTRAINT container_configs_pkey PRIMARY KEY (tool_version_id);


--
-- Name: agent_runs conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: dataset_versions dataset_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_pkey PRIMARY KEY (id);


--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (id);


--
-- Name: llm_providers llm_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_pkey PRIMARY KEY (id);


--
-- Name: llm_providers llm_providers_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_slug_key UNIQUE (slug);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: object_store_buckets object_store_buckets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_store_buckets
    ADD CONSTRAINT object_store_buckets_pkey PRIMARY KEY (id);


--
-- Name: orgs orgs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orgs
    ADD CONSTRAINT orgs_pkey PRIMARY KEY (id);


--
-- Name: pipelines pipeline_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT pipeline_definitions_pkey PRIMARY KEY (id);


--
-- Name: pipeline_run_artifacts pipeline_run_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_run_artifacts
    ADD CONSTRAINT pipeline_run_artifacts_pkey PRIMARY KEY (id);


--
-- Name: pipeline_runs pipeline_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_pkey PRIMARY KEY (id);


--
-- Name: pipeline_step_runs pipeline_step_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_step_runs
    ADD CONSTRAINT pipeline_step_runs_pkey PRIMARY KEY (id);


--
-- Name: pipeline_versions pipeline_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_versions
    ADD CONSTRAINT pipeline_versions_pkey PRIMARY KEY (id);


--
-- Name: platform_settings platform_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_settings
    ADD CONSTRAINT platform_settings_pkey PRIMARY KEY (key);


--
-- Name: tool_pypi_configs pypi_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_pypi_configs
    ADD CONSTRAINT pypi_configs_pkey PRIMARY KEY (tool_version_id);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: task_run_artifacts task_run_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_artifacts
    ADD CONSTRAINT task_run_artifacts_pkey PRIMARY KEY (id);


--
-- Name: task_run_events task_run_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_events
    ADD CONSTRAINT task_run_events_pkey PRIMARY KEY (id);


--
-- Name: task_runs task_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pkey PRIMARY KEY (id);


--
-- Name: teams teams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: tool_human_configs tool_human_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_human_configs
    ADD CONSTRAINT tool_human_configs_pkey PRIMARY KEY (tool_version_id);


--
-- Name: tool_run_artifacts tool_run_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_run_artifacts
    ADD CONSTRAINT tool_run_artifacts_pkey PRIMARY KEY (id);


--
-- Name: tool_runs tool_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_runs
    ADD CONSTRAINT tool_runs_pkey PRIMARY KEY (id);


--
-- Name: tool_versions tool_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_versions
    ADD CONSTRAINT tool_versions_pkey PRIMARY KEY (id);


--
-- Name: tools tools_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tools
    ADD CONSTRAINT tools_pkey PRIMARY KEY (id);


--
-- Name: compute_artifacts uq_artifact_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compute_artifacts
    ADD CONSTRAINT uq_artifact_identity UNIQUE (kind, name, version, registry_url);


--
-- Name: subscriptions uq_subscription; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT uq_subscription UNIQUE (user_id, resource_type, resource_id);


--
-- Name: teams uq_teams_org_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT uq_teams_org_slug UNIQUE (org_id, slug);


--
-- Name: users users_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_external_id_key UNIQUE (external_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_agent_runs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_agent_id ON public.agent_runs USING btree (agent_id);


--
-- Name: ix_agent_runs_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_org_id ON public.agent_runs USING btree (org_id);


--
-- Name: ix_agent_task_runs_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_task_runs_agent_id ON public.agent_task_runs USING btree (agent_id);


--
-- Name: ix_agent_task_runs_agentic_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_task_runs_agentic_run_id ON public.agent_task_runs USING btree (conversation_id);


--
-- Name: ix_agent_task_runs_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_task_runs_org_id ON public.agent_task_runs USING btree (org_id);


--
-- Name: ix_agents_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_name ON public.agents USING btree (name);


--
-- Name: ix_agents_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agents_org_id ON public.agents USING btree (org_id);


--
-- Name: ix_agents_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_agents_slug ON public.agents USING btree (slug);


--
-- Name: ix_api_keys_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_prefix ON public.api_keys USING btree (prefix);


--
-- Name: ix_app_launches_app_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_app_launches_app_id ON public.app_launches USING btree (app_id);


--
-- Name: ix_app_launches_app_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_app_launches_app_id_created_at ON public.app_launches USING btree (app_id, created_at DESC);


--
-- Name: ix_app_launches_launched_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_app_launches_launched_by ON public.app_launches USING btree (launched_by);


--
-- Name: ix_app_launches_launched_by_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_app_launches_launched_by_created_at ON public.app_launches USING btree (launched_by, created_at DESC);


--
-- Name: ix_app_launches_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_app_launches_org_id ON public.app_launches USING btree (org_id);


--
-- Name: ix_apps_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_apps_name ON public.apps USING btree (name);


--
-- Name: ix_apps_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_apps_org_id ON public.apps USING btree (org_id);


--
-- Name: ix_apps_runtime_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_apps_runtime_status ON public.apps USING btree (runtime_status);


--
-- Name: ix_apps_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_apps_slug ON public.apps USING btree (slug);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_timestamp ON public.audit_logs USING btree ("timestamp");


--
-- Name: ix_compute_artifacts_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compute_artifacts_kind ON public.compute_artifacts USING btree (kind);


--
-- Name: ix_compute_artifacts_origin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compute_artifacts_origin ON public.compute_artifacts USING btree (origin);


--
-- Name: ix_compute_artifacts_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compute_artifacts_status ON public.compute_artifacts USING btree (status);


--
-- Name: ix_compute_backends_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compute_backends_name ON public.compute_backends USING btree (name);


--
-- Name: ix_dataset_versions_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dataset_versions_dataset_id ON public.dataset_versions USING btree (dataset_id);


--
-- Name: ix_dataset_versions_source_bucket_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dataset_versions_source_bucket_id ON public.dataset_versions USING btree (source_bucket_id);


--
-- Name: ix_datasets_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_datasets_name ON public.datasets USING btree (name);


--
-- Name: ix_datasets_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_datasets_org_id ON public.datasets USING btree (org_id);


--
-- Name: ix_datasets_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_datasets_slug ON public.datasets USING btree (slug);


--
-- Name: ix_llm_providers_is_default; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_is_default ON public.llm_providers USING btree (is_default);


--
-- Name: ix_llm_providers_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_org_id ON public.llm_providers USING btree (org_id);


--
-- Name: ix_llm_providers_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_llm_providers_slug ON public.llm_providers USING btree (slug);


--
-- Name: ix_notifications_is_read; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_is_read ON public.notifications USING btree (is_read);


--
-- Name: ix_notifications_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_id ON public.notifications USING btree (user_id);


--
-- Name: ix_object_store_buckets_is_default; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_store_buckets_is_default ON public.object_store_buckets USING btree (is_default);


--
-- Name: ix_object_store_buckets_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_object_store_buckets_org_id ON public.object_store_buckets USING btree (org_id);


--
-- Name: ix_object_store_buckets_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_object_store_buckets_slug ON public.object_store_buckets USING btree (slug);


--
-- Name: ix_orgs_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_orgs_slug ON public.orgs USING btree (slug);


--
-- Name: ix_pipeline_definitions_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_definitions_name ON public.pipelines USING btree (name);


--
-- Name: ix_pipeline_definitions_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_definitions_org_id ON public.pipelines USING btree (org_id);


--
-- Name: ix_pipeline_definitions_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_pipeline_definitions_slug ON public.pipelines USING btree (slug);


--
-- Name: ix_pipeline_run_artifacts_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_run_artifacts_run_id ON public.pipeline_run_artifacts USING btree (run_id);


--
-- Name: ix_pipeline_runs_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_runs_org_id ON public.pipeline_runs USING btree (org_id);


--
-- Name: ix_pipeline_runs_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_runs_version_id ON public.pipeline_runs USING btree (version_id);


--
-- Name: ix_pipeline_step_runs_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_step_runs_run_id ON public.pipeline_step_runs USING btree (run_id);


--
-- Name: ix_pipeline_versions_definition_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipeline_versions_definition_id ON public.pipeline_versions USING btree (pipeline_id);


--
-- Name: ix_pipelines_topology_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pipelines_topology_hash ON public.pipelines USING btree (topology_hash);


--
-- Name: ix_roles_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_roles_name ON public.roles USING btree (name);


--
-- Name: ix_subscriptions_resource_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_resource_id ON public.subscriptions USING btree (resource_id);


--
-- Name: ix_subscriptions_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_resource_type ON public.subscriptions USING btree (resource_type);


--
-- Name: ix_subscriptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_subscriptions_user_id ON public.subscriptions USING btree (user_id);


--
-- Name: ix_task_run_artifacts_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_run_artifacts_event ON public.task_run_artifacts USING btree (event_id);


--
-- Name: ix_task_run_artifacts_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_run_artifacts_org_status ON public.task_run_artifacts USING btree (org_id, status);


--
-- Name: ix_task_run_artifacts_task_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_run_artifacts_task_run ON public.task_run_artifacts USING btree (task_run_id);


--
-- Name: ix_task_run_events_task_run_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_run_events_task_run_time ON public.task_run_events USING btree (task_run_id, occurred_at);


--
-- Name: ix_task_runs_assigned_team; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_assigned_team ON public.task_runs USING btree (assigned_team_slug);


--
-- Name: ix_task_runs_assigned_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_assigned_user ON public.task_runs USING btree (assigned_user_id);


--
-- Name: ix_task_runs_due_open; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_due_open ON public.task_runs USING btree (due_at) WHERE (outcome IS NULL);


--
-- Name: ix_task_runs_org_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_org_status ON public.task_runs USING btree (org_id, status);


--
-- Name: ix_task_runs_pipeline_step; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_pipeline_step ON public.task_runs USING btree (pipeline_run_id, step_name);


--
-- Name: ix_task_runs_tool; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_task_runs_tool ON public.task_runs USING btree (tool_id);


--
-- Name: ix_teams_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_teams_slug ON public.teams USING btree (slug);


--
-- Name: ix_tool_run_artifacts_run_io; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tool_run_artifacts_run_io ON public.tool_run_artifacts USING btree (tool_run_id, io_type);


--
-- Name: ix_tool_run_artifacts_tool_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tool_run_artifacts_tool_run_id ON public.tool_run_artifacts USING btree (tool_run_id);


--
-- Name: ix_tool_runs_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tool_runs_org_id ON public.tool_runs USING btree (org_id);


--
-- Name: ix_tool_runs_tool_version_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tool_runs_tool_version_id ON public.tool_runs USING btree (tool_version_id);


--
-- Name: ix_tool_versions_tool_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tool_versions_tool_id ON public.tool_versions USING btree (tool_id);


--
-- Name: ix_tools_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tools_name ON public.tools USING btree (name);


--
-- Name: ix_tools_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tools_org_id ON public.tools USING btree (org_id);


--
-- Name: ix_tools_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tools_slug ON public.tools USING btree (slug);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: agents agent_definitions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agent_definitions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: agents agent_definitions_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agent_definitions_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: agent_task_runs agent_runs_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_task_runs
    ADD CONSTRAINT agent_runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_task_runs agent_runs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_task_runs
    ADD CONSTRAINT agent_runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: agent_task_runs agent_runs_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_task_runs
    ADD CONSTRAINT agent_runs_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.users(id);


--
-- Name: agent_task_runs agent_task_runs_agentic_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_task_runs
    ADD CONSTRAINT agent_task_runs_agentic_run_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: app_launches app_launches_app_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_launches
    ADD CONSTRAINT app_launches_app_id_fkey FOREIGN KEY (app_id) REFERENCES public.apps(id) ON DELETE CASCADE;


--
-- Name: app_launches app_launches_launched_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_launches
    ADD CONSTRAINT app_launches_launched_by_fkey FOREIGN KEY (launched_by) REFERENCES public.users(id);


--
-- Name: app_launches app_launches_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_launches
    ADD CONSTRAINT app_launches_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: apps apps_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apps
    ADD CONSTRAINT apps_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: apps apps_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apps
    ADD CONSTRAINT apps_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: apps apps_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apps
    ADD CONSTRAINT apps_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: compute_artifacts compute_artifacts_published_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compute_artifacts
    ADD CONSTRAINT compute_artifacts_published_by_fkey FOREIGN KEY (published_by) REFERENCES public.users(id);


--
-- Name: tool_docker_configs container_configs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_docker_configs
    ADD CONSTRAINT container_configs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id) ON DELETE CASCADE;


--
-- Name: agent_runs conversations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT conversations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;


--
-- Name: agent_runs conversations_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT conversations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: agent_runs conversations_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT conversations_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: dataset_versions dataset_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: dataset_versions dataset_versions_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(id) ON DELETE CASCADE;


--
-- Name: datasets datasets_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: datasets datasets_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: dataset_versions fk_dataset_versions_source_bucket; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT fk_dataset_versions_source_bucket FOREIGN KEY (source_bucket_id) REFERENCES public.object_store_buckets(id) ON DELETE SET NULL;


--
-- Name: pipeline_runs fk_pipeline_runs_restarted_from; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT fk_pipeline_runs_restarted_from FOREIGN KEY (restarted_from) REFERENCES public.pipeline_runs(id);


--
-- Name: pipeline_runs fk_pipeline_runs_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT fk_pipeline_runs_version_id FOREIGN KEY (version_id) REFERENCES public.pipeline_versions(id) ON DELETE CASCADE;


--
-- Name: pipeline_versions fk_pipeline_versions_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_versions
    ADD CONSTRAINT fk_pipeline_versions_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: pipelines fk_pipelines_forked_from; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT fk_pipelines_forked_from FOREIGN KEY (forked_from) REFERENCES public.pipelines(id);


--
-- Name: pipelines fk_pipelines_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT fk_pipelines_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: task_run_events fk_task_run_events_parent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_events
    ADD CONSTRAINT fk_task_run_events_parent FOREIGN KEY (parent_event_id) REFERENCES public.task_run_events(id) ON DELETE SET NULL;


--
-- Name: task_runs fk_task_runs_assigned_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT fk_task_runs_assigned_user FOREIGN KEY (assigned_user_id) REFERENCES public.users(id);


--
-- Name: task_runs fk_task_runs_project_lead; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT fk_task_runs_project_lead FOREIGN KEY (project_lead_id) REFERENCES public.users(id);


--
-- Name: task_runs fk_task_runs_submitted_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT fk_task_runs_submitted_by FOREIGN KEY (finished_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: tool_docker_configs fk_tool_docker_configs_artifact_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_docker_configs
    ADD CONSTRAINT fk_tool_docker_configs_artifact_id FOREIGN KEY (artifact_id) REFERENCES public.compute_artifacts(id) ON DELETE SET NULL;


--
-- Name: tool_pypi_configs fk_tool_pypi_configs_artifact_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_pypi_configs
    ADD CONSTRAINT fk_tool_pypi_configs_artifact_id FOREIGN KEY (artifact_id) REFERENCES public.compute_artifacts(id) ON DELETE SET NULL;


--
-- Name: llm_providers llm_providers_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: llm_providers llm_providers_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: object_store_buckets object_store_buckets_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_store_buckets
    ADD CONSTRAINT object_store_buckets_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: object_store_buckets object_store_buckets_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_store_buckets
    ADD CONSTRAINT object_store_buckets_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: pipelines pipeline_definitions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT pipeline_definitions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pipelines pipeline_definitions_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipelines
    ADD CONSTRAINT pipeline_definitions_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: pipeline_run_artifacts pipeline_run_artifacts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_run_artifacts
    ADD CONSTRAINT pipeline_run_artifacts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.pipeline_runs(id) ON DELETE CASCADE;


--
-- Name: pipeline_runs pipeline_runs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: pipeline_runs pipeline_runs_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.users(id);


--
-- Name: pipeline_step_runs pipeline_step_runs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_step_runs
    ADD CONSTRAINT pipeline_step_runs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.pipeline_runs(id) ON DELETE CASCADE;


--
-- Name: pipeline_step_runs pipeline_step_runs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_step_runs
    ADD CONSTRAINT pipeline_step_runs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id);


--
-- Name: pipeline_versions pipeline_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_versions
    ADD CONSTRAINT pipeline_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pipeline_versions pipeline_versions_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_versions
    ADD CONSTRAINT pipeline_versions_definition_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.pipelines(id) ON DELETE CASCADE;


--
-- Name: tool_pypi_configs pypi_configs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_pypi_configs
    ADD CONSTRAINT pypi_configs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id) ON DELETE CASCADE;


--
-- Name: subscriptions subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: task_run_artifacts task_run_artifacts_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_artifacts
    ADD CONSTRAINT task_run_artifacts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: task_run_artifacts task_run_artifacts_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_artifacts
    ADD CONSTRAINT task_run_artifacts_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.task_run_events(id) ON DELETE SET NULL;


--
-- Name: task_run_artifacts task_run_artifacts_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_artifacts
    ADD CONSTRAINT task_run_artifacts_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: task_run_artifacts task_run_artifacts_task_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_artifacts
    ADD CONSTRAINT task_run_artifacts_task_run_id_fkey FOREIGN KEY (task_run_id) REFERENCES public.task_runs(id) ON DELETE CASCADE;


--
-- Name: task_run_events task_run_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_events
    ADD CONSTRAINT task_run_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);


--
-- Name: task_run_events task_run_events_task_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_run_events
    ADD CONSTRAINT task_run_events_task_run_id_fkey FOREIGN KEY (task_run_id) REFERENCES public.task_runs(id) ON DELETE CASCADE;


--
-- Name: task_runs task_runs_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_created_by_fkey FOREIGN KEY (started_by) REFERENCES public.users(id);


--
-- Name: task_runs task_runs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: task_runs task_runs_pipeline_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pipeline_run_id_fkey FOREIGN KEY (pipeline_run_id) REFERENCES public.pipeline_runs(id) ON DELETE SET NULL;


--
-- Name: task_runs task_runs_pipeline_step_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pipeline_step_run_id_fkey FOREIGN KEY (pipeline_step_run_id) REFERENCES public.pipeline_step_runs(id) ON DELETE SET NULL;


--
-- Name: task_runs task_runs_tool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_tool_id_fkey FOREIGN KEY (tool_id) REFERENCES public.tools(id) ON DELETE RESTRICT;


--
-- Name: task_runs task_runs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id) ON DELETE RESTRICT;


--
-- Name: teams teams_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id) ON DELETE CASCADE;


--
-- Name: tool_human_configs tool_human_configs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_human_configs
    ADD CONSTRAINT tool_human_configs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id) ON DELETE CASCADE;


--
-- Name: tool_run_artifacts tool_run_artifacts_tool_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_run_artifacts
    ADD CONSTRAINT tool_run_artifacts_tool_run_id_fkey FOREIGN KEY (tool_run_id) REFERENCES public.tool_runs(id) ON DELETE CASCADE;


--
-- Name: tool_runs tool_runs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_runs
    ADD CONSTRAINT tool_runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: tool_runs tool_runs_restarted_from_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_runs
    ADD CONSTRAINT tool_runs_restarted_from_fkey FOREIGN KEY (restarted_from) REFERENCES public.tool_runs(id);


--
-- Name: tool_runs tool_runs_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_runs
    ADD CONSTRAINT tool_runs_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.users(id);


--
-- Name: tool_runs tool_runs_tool_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_runs
    ADD CONSTRAINT tool_runs_tool_version_id_fkey FOREIGN KEY (tool_version_id) REFERENCES public.tool_versions(id) ON DELETE CASCADE;


--
-- Name: tool_versions tool_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_versions
    ADD CONSTRAINT tool_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: tool_versions tool_versions_tool_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_versions
    ADD CONSTRAINT tool_versions_tool_id_fkey FOREIGN KEY (tool_id) REFERENCES public.tools(id) ON DELETE CASCADE;


--
-- Name: tools tools_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tools
    ADD CONSTRAINT tools_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: tools tools_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tools
    ADD CONSTRAINT tools_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: users users_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.orgs(id);


--
-- Name: users users_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: users users_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);
"""


def upgrade() -> None:
    op.execute(SCHEMA_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.agent_task_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.agent_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_run_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_docker_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_pypi_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_human_configs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tool_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.tools CASCADE")
    op.execute("DROP TABLE IF EXISTS public.pipeline_run_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS public.pipeline_step_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.pipeline_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.pipeline_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.pipelines CASCADE")
    op.execute("DROP TABLE IF EXISTS public.task_run_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS public.task_run_events CASCADE")
    op.execute("DROP TABLE IF EXISTS public.task_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.dataset_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.datasets CASCADE")
    op.execute("DROP TABLE IF EXISTS public.app_launches CASCADE")
    op.execute("DROP TABLE IF EXISTS public.apps CASCADE")
    op.execute("DROP TABLE IF EXISTS public.compute_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS public.compute_backends CASCADE")
    op.execute("DROP TABLE IF EXISTS public.subscriptions CASCADE")
    op.execute("DROP TABLE IF EXISTS public.notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS public.platform_settings CASCADE")
    op.execute("DROP TABLE IF EXISTS public.llm_providers CASCADE")
    op.execute("DROP TABLE IF EXISTS public.object_store_buckets CASCADE")
    op.execute("DROP TABLE IF EXISTS public.audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS public.api_keys CASCADE")
    op.execute("DROP TABLE IF EXISTS public.agents CASCADE")
    op.execute("DROP TABLE IF EXISTS public.roles CASCADE")
    op.execute("DROP TABLE IF EXISTS public.teams CASCADE")
    op.execute("DROP TABLE IF EXISTS public.users CASCADE")
    op.execute("DROP TABLE IF EXISTS public.orgs CASCADE")
    op.execute("DROP TYPE IF EXISTS public.agent_run_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.app_auth_mode CASCADE")
    op.execute("DROP TYPE IF EXISTS public.app_launch_mode CASCADE")
    op.execute("DROP TYPE IF EXISTS public.app_runtime_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.app_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.artifact_kind CASCADE")
    op.execute("DROP TYPE IF EXISTS public.artifact_origin CASCADE")
    op.execute("DROP TYPE IF EXISTS public.artifact_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.compute_backend_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.dataset_version_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.pipeline_run_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.pipeline_type CASCADE")
    op.execute("DROP TYPE IF EXISTS public.pipeline_version_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.step_run_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.task_run_actor_type CASCADE")
    op.execute("DROP TYPE IF EXISTS public.task_run_outcome CASCADE")
    op.execute("DROP TYPE IF EXISTS public.task_run_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.tool_run_status CASCADE")
    op.execute("DROP TYPE IF EXISTS public.tool_type CASCADE")
    op.execute("DROP TYPE IF EXISTS public.tool_version_status CASCADE")
