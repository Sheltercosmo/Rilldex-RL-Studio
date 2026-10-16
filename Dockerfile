FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY tracker ./tracker
COPY rilldex ./rilldex
RUN python -m pip wheel --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-deps /wheels/*.whl \
    && useradd --uid 10001 --create-home rilldex \
    && mkdir -p /data /outputs && chown rilldex:rilldex /data
USER rilldex
WORKDIR /data
EXPOSE 8765
ENTRYPOINT ["rilldex"]
CMD ["--db", "/data/workspace.sqlite", "start", "--container"]
