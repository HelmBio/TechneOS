"""AWS Batch compute backend.

Submits containerised pipeline steps as AWS Batch jobs, polls their
status via CloudWatch, and retrieves logs from CloudWatch Logs.

Prerequisites
-------------
* An AWS Batch **Job Queue** and **Compute Environment** must exist.
* A **Job Definition** (registered externally or via IaC) whose
  container image and resource requirements can be overridden at
  submit time.
* The process running this code must have AWS credentials with
  ``batch:SubmitJob``, ``batch:DescribeJobs``, ``batch:TerminateJob``,
  and ``logs:GetLogEvents`` permissions.

Environment variables
---------------------
``AWS_BATCH_JOB_QUEUE``
    Default Batch job queue name.
``AWS_BATCH_JOB_DEFINITION``
    Default Batch job definition name (used if the step does not
    specify one in ``extra``).
``AWS_REGION``
    AWS region (also read by boto3 default chain).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from backends.base import ComputeBackend, JobResult, JobSpec, JobStatus

logger = logging.getLogger(__name__)

# AWS Batch job status → platform normalised status
_BATCH_STATUS_MAP: dict[str, JobStatus] = {
    "SUBMITTED": JobStatus.PENDING,
    "PENDING": JobStatus.PENDING,
    "RUNNABLE": JobStatus.PENDING,
    "STARTING": JobStatus.RUNNING,
    "RUNNING": JobStatus.RUNNING,
    "SUCCEEDED": JobStatus.COMPLETED,
    "FAILED": JobStatus.FAILED,
}


class AWSBatchBackend(ComputeBackend):
    """Execute jobs on AWS Batch.

    Batch containers run on remote EC2 instances with no shared filesystem,
    so the work directory is staged via S3:

    - ``submit_job`` uploads ``{work_dir_host}/`` → ``s3://{bucket}/{prefix}/``
    - Container env vars ``TECHNEOS_BATCH_WORK_BUCKET`` and ``TECHNEOS_S3_WORK_PREFIX``
      tell the tool-runtime to sync S3 → ``/work`` at startup and
      ``/work/output/`` → S3 at exit. The bucket is read host-side from
      ``AWS_BATCH_WORK_BUCKET`` but injected into the container as
      ``TECHNEOS_BATCH_WORK_BUCKET`` — Batch strips any ``AWS_BATCH``-prefixed var.
    - ``collect_outputs`` downloads from S3 back to local.
    - ``cleanup_container`` deletes the S3 prefix.
    """

    def __init__(
        self,
        job_queue: str | None = None,
        job_definition: str | None = None,
        region: str | None = None,
        s3_work_bucket: str | None = None,
    ) -> None:
        self._job_queue = job_queue or os.getenv("AWS_BATCH_JOB_QUEUE", "techneos-job-queue")
        self._job_definition = job_definition or os.getenv(
            "AWS_BATCH_JOB_DEFINITION", "techneos-tool-job"
        )
        self._region = region or os.getenv("AWS_REGION", "us-east-1")
        self._s3_work_bucket = s3_work_bucket or os.getenv("AWS_BATCH_WORK_BUCKET", "techneos-data")
        self._batch: Any = None
        self._logs_client: Any = None
        self._s3: Any = None
        self._job_s3_prefixes: dict[str, str] = {}

    @property
    def batch(self) -> Any:
        if self._batch is None:
            self._batch = boto3.client("batch", region_name=self._region)
        return self._batch

    @property
    def logs_client(self) -> Any:
        if self._logs_client is None:
            self._logs_client = boto3.client("logs", region_name=self._region)
        return self._logs_client

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self._region)
        return self._s3

    def _stage_to_s3(self, work_dir_host: str, s3_prefix: str) -> None:
        """Upload the local work directory to S3."""
        work_path = Path(work_dir_host)
        if not work_path.exists():
            return
        for file_path in work_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(work_path).as_posix()
            s3_key = f"{s3_prefix}/{rel}"
            self.s3.upload_file(str(file_path), self._s3_work_bucket, s3_key)
        logger.info("Staged work dir to s3://%s/%s", self._s3_work_bucket, s3_prefix)

    def _collect_from_s3(self, s3_prefix: str, local_dir: str) -> dict[str, bytes]:
        """Download output files from S3 and return as {name: bytes}."""
        output_prefix = f"{s3_prefix}/output/"
        paginator = self.s3.get_paginator("list_objects_v2")
        files: dict[str, bytes] = {}
        for page in paginator.paginate(Bucket=self._s3_work_bucket, Prefix=output_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                rel = key[len(output_prefix):]
                if not rel:
                    continue
                local_path = Path(local_dir) / rel
                local_path.parent.mkdir(parents=True, exist_ok=True)
                self.s3.download_file(self._s3_work_bucket, key, str(local_path))
                files[rel] = local_path.read_bytes()
        return files

    def _cleanup_s3(self, s3_prefix: str) -> None:
        """Delete all objects under the S3 work prefix."""
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._s3_work_bucket, Prefix=s3_prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self.s3.delete_objects(
                    Bucket=self._s3_work_bucket,
                    Delete={"Objects": objects},
                )

    def _ecr_image_uri(self, short_name: str, tag: str) -> str:
        """Expand a short image name (e.g. ``techneos/tool``) to a full ECR URI."""
        if ".dkr.ecr." in short_name:
            return f"{short_name}:{tag}"
        sts = boto3.client("sts", region_name=self._region)
        account = sts.get_caller_identity()["Account"]
        return f"{account}.dkr.ecr.{self._region}.amazonaws.com/{short_name}:{tag}"

    def _resolve_job_definition(self, spec: JobSpec) -> str:
        """Return a job definition ARN whose image matches the spec.

        Batch ``containerOverrides`` does not support overriding the image,
        so when the spec requests an image different from the base job
        definition we register a new revision with the correct image.
        """
        base_def = spec.extra.get("job_definition", self._job_definition)
        if not spec.image:
            return base_def

        image_ref = self._ecr_image_uri(spec.image, spec.tag)

        resp = self.batch.describe_job_definitions(
            jobDefinitionName=base_def, status="ACTIVE",
        )
        defs = resp.get("jobDefinitions", [])
        if not defs:
            return base_def

        latest = sorted(defs, key=lambda d: d["revision"])[-1]
        current_image = latest.get("containerProperties", {}).get("image", "")
        if current_image == image_ref:
            return base_def

        container_props = dict(latest["containerProperties"])
        container_props["image"] = image_ref
        reg_resp = self.batch.register_job_definition(
            jobDefinitionName=base_def,
            type=latest["type"],
            containerProperties=container_props,
            platformCapabilities=latest.get("platformCapabilities", ["EC2"]),
            retryStrategy=latest.get("retryStrategy", {"attempts": 1}),
            timeout=latest.get("timeout", {}),
        )
        new_arn = reg_resp["jobDefinitionArn"]
        logger.info("Registered job definition revision %s (image=%s)", new_arn, image_ref)
        return new_arn

    async def submit_job(self, spec: JobSpec) -> str:
        """Submit a Batch job and return the AWS job id."""

        # Stage work directory to S3 so the container can access inputs.
        # Use work_dir_local (scheduler-container path) for the upload since
        # work_dir_host is a host-translated path not accessible from here.
        s3_prefix = f"batch-work/{spec.run_id}/{spec.step_name}"
        stage_dir = spec.work_dir_local or spec.work_dir_host
        if stage_dir:
            await asyncio.to_thread(self._stage_to_s3, stage_dir, s3_prefix)

        def _submit() -> str:
            env = dict(spec.environment)
            # Translate the host-side config (AWS_BATCH_WORK_BUCKET) to a
            # non-reserved name for the container: AWS Batch silently strips any
            # env var whose name starts with "AWS_BATCH" (reserved for the
            # service), so the bucket must be injected as TECHNEOS_BATCH_WORK_BUCKET.
            env["TECHNEOS_BATCH_WORK_BUCKET"] = self._s3_work_bucket
            env["TECHNEOS_S3_WORK_PREFIX"] = s3_prefix

            container_overrides: dict[str, Any] = {
                "environment": [{"name": k, "value": v} for k, v in env.items()],
                "resourceRequirements": [
                    {"type": "VCPU", "value": spec.cpu},
                    {"type": "MEMORY", "value": _memory_to_mib(spec.memory)},
                ],
            }

            if spec.command:
                container_overrides["command"] = spec.command

            if spec.gpu > 0:
                container_overrides["resourceRequirements"].append(
                    {"type": "GPU", "value": str(spec.gpu)}
                )

            job_def = self._resolve_job_definition(spec)
            job_queue = spec.extra.get("job_queue", self._job_queue)

            resp = self.batch.submit_job(
                jobName=f"techneos-{spec.run_id[:8]}-{spec.step_name}",
                jobQueue=job_queue,
                jobDefinition=job_def,
                containerOverrides=container_overrides,
                parameters={
                    "run_id": spec.run_id,
                    "step_name": spec.step_name,
                },
                tags={
                    "techneos:run_id": spec.run_id,
                    "techneos:step_name": spec.step_name,
                },
            )
            job_id: str = resp["jobId"]
            logger.info(
                "Submitted AWS Batch job %s (queue=%s, def=%s)",
                job_id,
                job_queue,
                job_def,
            )
            return job_id

        job_id = await asyncio.to_thread(_submit)
        self._job_s3_prefixes[job_id] = s3_prefix
        return job_id

    async def get_job_status(self, job_id: str) -> JobResult:
        def _describe() -> JobResult:
            resp = self.batch.describe_jobs(jobs=[job_id])
            jobs = resp.get("jobs", [])
            if not jobs:
                return JobResult(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error_message="Job not found in AWS Batch",
                )

            job = jobs[0]
            aws_status = job.get("status", "SUBMITTED")
            status = _BATCH_STATUS_MAP.get(aws_status, JobStatus.PENDING)

            exit_code = None
            error_msg = None
            container = job.get("container", {})
            if aws_status in ("SUCCEEDED", "FAILED"):
                exit_code = container.get("exitCode")
                error_msg = container.get("reason")

            return JobResult(
                job_id=job_id,
                status=status,
                exit_code=exit_code,
                error_message=error_msg,
            )

        return await asyncio.to_thread(_describe)

    async def cancel_job(self, job_id: str) -> None:
        def _terminate() -> None:
            try:
                self.batch.terminate_job(jobId=job_id, reason="Cancelled by platform")
                logger.info("Terminated AWS Batch job %s", job_id)
            except ClientError as e:
                logger.warning("Failed to terminate Batch job %s: %s", job_id, e)

        await asyncio.to_thread(_terminate)

    async def get_logs(self, job_id: str, tail: int = 500) -> str:
        """Retrieve logs from CloudWatch Logs.

        AWS Batch streams container stdout/stderr to a CloudWatch log
        group named ``/aws/batch/job``.  The log stream name follows
        the pattern ``<job-definition>/<container-name>/<ecs-task-id>``.
        """

        def _fetch() -> str:
            # Describe job to get the log stream name
            try:
                resp = self.batch.describe_jobs(jobs=[job_id])
                jobs = resp.get("jobs", [])
                if not jobs:
                    return ""
                container = jobs[0].get("container", {})
                log_stream = container.get("logStreamName")
                if not log_stream:
                    return ""

                log_resp = self.logs_client.get_log_events(
                    logGroupName="/aws/batch/job",
                    logStreamName=log_stream,
                    limit=tail,
                    startFromHead=False,
                )
                events = log_resp.get("events", [])
                return "\n".join(e.get("message", "") for e in events)
            except ClientError as e:
                logger.warning("Failed to fetch logs for job %s: %s", job_id, e)
                return ""

        return await asyncio.to_thread(_fetch)


    async def collect_outputs(
        self, job_id: str, work_dir_host: str | None = None,
    ) -> dict[str, bytes]:
        """Download output files from S3 after job completion.

        Outputs live in S3 (the container has no shared filesystem), so they
        are downloaded into scratch space and read into the returned bytes
        dict. ``work_dir_host`` is ignored: it is a host-translated path (e.g.
        ``/Users/...``) that is not accessible from inside the scheduler
        container where this runs — we always use a scheduler-local temp dir.
        """
        s3_prefix = self._job_s3_prefixes.get(job_id)
        if not s3_prefix:
            return {}

        import tempfile

        local_dir = tempfile.mkdtemp(prefix="techneos-batch-out-")
        return await asyncio.to_thread(self._collect_from_s3, s3_prefix, local_dir)

    async def cleanup_container(self, job_id: str) -> None:
        """Delete the S3 work prefix for this job."""
        s3_prefix = self._job_s3_prefixes.pop(job_id, None)
        if s3_prefix:
            await asyncio.to_thread(self._cleanup_s3, s3_prefix)


def _memory_to_mib(mem: str) -> str:
    """Convert memory string to MiB string for AWS Batch."""
    mem = mem.strip()
    try:
        if mem.endswith("Gi"):
            return str(int(float(mem[:-2]) * 1024))
        if mem.endswith("Mi"):
            return str(int(float(mem[:-2])))
        if mem.endswith("G"):
            return str(int(float(mem[:-1]) * 1000 / 1.048576))
        if mem.endswith("M"):
            return str(int(float(mem[:-1]) / 1.048576))
        return mem
    except (ValueError, TypeError):
        return "2048"
