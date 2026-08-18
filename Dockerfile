FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY pyproject.toml README.md main.py ./
COPY reviewer/ reviewer/
RUN pip install --no-cache-dir setuptools && \
    pip wheel --no-cache-dir --no-build-isolation --no-deps --wheel-dir /build/dist . && \
    pip install --no-cache-dir --no-deps --prefix=/install /build/dist/*.whl

FROM python:3.12-slim

RUN groupadd --gid 1000 reviewer && useradd --uid 1000 --gid reviewer --create-home reviewer

COPY --from=builder /install /usr/local

USER reviewer
WORKDIR /home/reviewer

EXPOSE 8000

CMD ["ai-review-server"]
