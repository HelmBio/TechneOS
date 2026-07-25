"""AWS primitives for the TechneOS platform.

One place for the cloud-provider-specific operations the platform relies on -
ECR (image push/pull auth, repositories) and CodeArtifact (wheel auth, package
listing) — built on a shared boto3 client factory.

Deliberately depends only on boto3 (not ``core``): callers pass the coordinates
they read from their own settings, so this package stays a thin, testable
boundary. The internet-facing gateway does **not** depend on this package — that
is how "the gateway holds no cloud credentials" is enforced by the dependency
graph, not by convention.
"""
