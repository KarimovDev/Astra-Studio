FROM golang:1.26-bookworm AS build

ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
WORKDIR /src
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio.git . \
    && test "$(git rev-parse HEAD)" = "$MINIO_COMMIT"

# Bound compiler concurrency for the 2 GB deployment host.
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOMEMLIMIT=768MiB
RUN MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go > /tmp/minio-ldflags \
    && go build -p 2 -trimpath -ldflags "$(cat /tmp/minio-ldflags)" -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z"
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
