# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/dotnet/sdk:10.0-noble AS lean-build
ARG DEBIAN_FRONTEND=noninteractive
ARG LEAN_REF=master

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone https://github.com/QuantConnect/Lean.git . \
    && git fetch --all --tags \
    && git checkout --detach "${LEAN_REF}" \
    && git rev-parse HEAD > /tmp/lean-commit.txt

COPY docker/patch_python_shutdown.py /tmp/patch_python_shutdown.py
RUN python3 /tmp/patch_python_shutdown.py /src/Common/Python/PythonInitializer.cs

RUN dotnet restore Launcher/QuantConnect.Lean.Launcher.csproj \
    && dotnet build Launcher/QuantConnect.Lean.Launcher.csproj \
         -c Release --no-restore

FROM mcr.microsoft.com/dotnet/runtime:10.0-noble AS runtime
ARG DEBIAN_FRONTEND=noninteractive
ARG RUNTIME_VERSION=1.1.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl bzip2 tini procps libgomp1 \
       libfontconfig1 libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11 is kept identical on Windows and macOS by running inside linux/amd64.
# conda-forge avoids the Anaconda default-channel Terms-of-Service prompt.
RUN curl -fsSL \
      https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
      -o /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p /opt/conda \
    && rm /tmp/miniconda.sh \
    && /opt/conda/bin/conda create -y -n alphaforge \
         --override-channels --channel conda-forge python=3.11.11 \
    && /opt/conda/bin/conda clean -afy

ENV PATH="/opt/conda/envs/alphaforge/bin:/opt/conda/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ALPHAFORGE_RUNTIME_VERSION=${RUNTIME_VERSION}

WORKDIR /app
COPY requirements.lock.txt /app/requirements.lock.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.lock.txt

COPY --from=lean-build /src/Launcher/bin/Release /opt/lean/Launcher/bin/Release
COPY --from=lean-build /src/Launcher/config.json /opt/lean/Launcher/config.json
COPY --from=lean-build /src/Data /opt/lean-default-data
COPY --from=lean-build /tmp/lean-commit.txt /opt/lean/LEAN_COMMIT.txt

COPY app /app/app
COPY worker /app/worker
COPY runtime_support /app/runtime_support
COPY config /app/config
COPY tools /app/tools
COPY docker/entrypoint.sh /usr/local/bin/alphaforge-entrypoint

RUN chmod +x /usr/local/bin/alphaforge-entrypoint \
    && mkdir -p /data/lean /runtime/results /runtime/jobs \
       /runtime/service /runtime/models /runtime/locks

EXPOSE 8081
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/alphaforge-entrypoint"]
CMD ["python", "-m", "uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8081"]
