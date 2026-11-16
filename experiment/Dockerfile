# Siansa Beats experiment: a trial of finding breakdowns and drops from a song's drums (siansa-dev #63). Temporary,
# and apart from Siansa Beats: only what the trial needs. Python, ffmpeg, torch for an NVIDIA GPU (it runs on the CPU
# too, slowly) and Demucs (Meta, MIT), whose model is downloaded while the image is built, so the service needs no
# internet: only your Navidrome.
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/echovaultstudio/siansa-beats" \
      org.opencontainers.image.description="Siansa Beats experiment: breakdowns and drops from a song's drums, for one Navidrome playlist (a trial)" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 TORCH_HOME=/models

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# The same torch as Siansa Beats' own image (CUDA 12.1: NVIDIA driver 525 or newer on the host), then Demucs, which
# takes the torch that's there.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu121
RUN pip install --index-url "$TORCH_INDEX" torch==2.3.1 torchaudio==2.3.1 \
 && pip install numpy==1.26.4 demucs==4.0.1 \
 && python -c "import torch, numpy, demucs; assert torch.__version__.startswith('2.3.1'), torch.__version__; assert numpy.__version__ == '1.26.4', numpy.__version__; print('torch', torch.__version__, 'demucs', demucs.__version__)"

# The model (htdemucs, 80 MB), kept in /models.
RUN mkdir -p /models && for try in 1 2 3 4 5; do \
      python -c "from demucs.pretrained import get_model; m = get_model('htdemucs'); print('htdemucs:', m.sources, m.samplerate)" \
        && break || { echo "download $try failed, trying again"; sleep 20; }; \
      [ "$try" != 5 ] || exit 1; \
    done && chmod -R a+rX /models

RUN useradd --uid 1000 --create-home beats && mkdir -p /data && chown beats /data
WORKDIR /app
COPY exp/ /app/exp/
COPY marks.json /app/marks.json
USER beats
# Demucs for real, as the service's user and without internet in mind: a made-up song's kick stops and comes back.
RUN python -m exp.selfcheck

ENV DATA_DIR=/data PORT=8095 NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility MALLOC_ARENA_MAX=2
VOLUME /data
EXPOSE 8095

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/api/health', timeout=4)"

CMD ["python", "-m", "exp.server"]
