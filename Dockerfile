FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md requirements.txt ./
COPY reviewer/ reviewer/
COPY main.py ./
RUN pip install --no-cache-dir --prefix=/install ".[server]"

FROM python:3.12-slim

RUN groupadd --gid 1000 reviewer && useradd --uid 1000 --gid reviewer --create-home reviewer

COPY --from=builder /install /usr/local

USER reviewer
WORKDIR /home/reviewer

EXPOSE 8000

CMD ["ai-review-server"]
