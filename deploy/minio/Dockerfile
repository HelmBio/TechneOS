# MinIO server + mc client, built from MinIO's own source at pinned releases.
#
# MinIO no longer publishes community container images: the minio/minio and
# minio/mc Docker Hub repos were deleted (Sep 2026), quay.io/minio is closed to
# anonymous pulls, and the community edition is distributed as source only. So
# we build the exact releases we pin and push the image to our own registry,
# next to the platform images (deploy/ec2/build-and-push.sh).
#
# VERSION is the MinIO server release and also the image tag (read by
# deploy/ec2/_image-catalog.sh). MC_VERSION is the bundled mc client, used by
# the minio healthcheck and by minio-init to create the bucket.
ARG VERSION=RELEASE.2025-09-07T16-13-09Z
ARG MC_VERSION=RELEASE.2025-08-13T08-35-41Z

# Compile natively and cross-build for the target: build-and-push.sh builds
# linux/amd64 from Macs too, and compiling MinIO under emulation is very slow.
FROM --platform=$BUILDPLATFORM golang:1.24-bookworm AS build
ARG VERSION
ARG MC_VERSION
ARG TARGETOS
ARG TARGETARCH
ENV CGO_ENABLED=0
WORKDIR /src
RUN git clone --depth 1 --branch "$VERSION" https://github.com/minio/minio.git minio \
 && cd minio \
 && LDFLAGS="$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go)" \
 && GOOS=$TARGETOS GOARCH=$TARGETARCH go build -tags kqueue -trimpath -ldflags "$LDFLAGS" -o /out/minio
RUN git clone --depth 1 --branch "$MC_VERSION" https://github.com/minio/mc.git mc \
 && cd mc \
 && LDFLAGS="$(MC_RELEASE=RELEASE go run buildscripts/gen-ldflags.go)" \
 && GOOS=$TARGETOS GOARCH=$TARGETARCH go build -tags kqueue -trimpath -ldflags "$LDFLAGS" -o /out/mc

FROM alpine:3.22
ARG VERSION
ARG MC_VERSION
LABEL org.opencontainers.image.title="minio" \
      org.opencontainers.image.description="MinIO ${VERSION} + mc ${MC_VERSION}, built from source" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
COPY --from=build /out/minio /out/mc /usr/bin/
ENV MC_CONFIG_DIR=/tmp/.mc
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/minio"]
CMD ["server", "/data"]
