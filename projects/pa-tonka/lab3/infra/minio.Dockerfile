# Official MinIO source release, AGPL-3.0; registry image is unavailable.
FROM golang:1.24.6-alpine3.22 AS build
WORKDIR /src
ADD --checksum=sha256:c9598dcce3440977e79f787f2ba0e7e4d92c8d556bd51e7cef3785bafd6635f3 https://codeload.github.com/minio/minio/tar.gz/refs/tags/RELEASE.2025-09-07T16-13-09Z /src/minio.tar.gz
RUN tar -xzf minio.tar.gz --strip-components=1 && rm minio.tar.gz
RUN CGO_ENABLED=0 go build -trimpath -o /out/minio .
FROM alpine:3.22.2
RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/licenses/minio/LICENSE
EXPOSE 9000
ENTRYPOINT ["/usr/local/bin/minio"]
