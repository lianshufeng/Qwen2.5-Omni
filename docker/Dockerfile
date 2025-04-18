# Dockerfile of qwenllm/qwen-omni:2.5-cu121

ARG CUDA_VERSION=12.1.0
ARG from=nvidia/cuda:${CUDA_VERSION}-cudnn8-devel-ubuntu22.04

FROM ${from} as base

ARG DEBIAN_FRONTEND=noninteractive

RUN apt update -y && \
    apt upgrade -y && \
    apt install -y --no-install-recommends \
        git \
        git-lfs \
        python3 \
        python3-pip \
        python3-dev \
        wget \
        curl \
        vim \
        libsndfile1 \
        ccache \
        software-properties-common \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 CMake 3.26.1
RUN wget https://github.com/Kitware/CMake/releases/download/v3.26.1/cmake-3.26.1-Linux-x86_64.sh \
    -q -O /tmp/cmake-install.sh \
    && chmod u+x /tmp/cmake-install.sh \
    && mkdir /opt/cmake-3.26.1 \
    && /tmp/cmake-install.sh --skip-license --prefix=/opt/cmake-3.26.1 \
    && rm /tmp/cmake-install.sh \
    && ln -s /opt/cmake-3.26.1/bin/* /usr/local/bin

RUN ln -s /usr/bin/python3 /usr/bin/python

RUN git lfs install

FROM base as dev

WORKDIR /

RUN mkdir -p /data/shared/Qwen

WORKDIR /data/shared/Qwen/

FROM dev as bundle_req

# 安装 PyTorch + xformers + transformers 等依赖
RUN --mount=type=cache,target=/root/.cache/pip pip3 install networkx==3.1

RUN --mount=type=cache,target=/root/.cache/pip pip3 install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 xformers==0.0.29.post2

RUN --mount=type=cache,target=/root/.cache/pip pip3 install \
    git+https://github.com/huggingface/transformers@3a1ead0aabed473eafe527915eea8c197d424356 && \
    pip3 install accelerate qwen-omni-utils modelscope_studio

FROM bundle_req as bundle_vllm

ARG BUNDLE_FLASH_ATTENTION=true

ENV MAX_JOBS=4
ENV NVCC_THREADS=1
ENV TORCH_CUDA_ARCH_LIST="7.0 7.5 8.0 8.6 8.9 9.0+PTX"
ENV VLLM_FA_CMAKE_GPU_ARCHES="80-real;90-real"
ENV CCACHE_DIR=/root/.cache/ccache

# 编译 flash-attention
RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/pip \
    if [ "$BUNDLE_FLASH_ATTENTION" = "true" ]; then \
        mkdir -p /data/shared/code && \
        pip install ninja && \
        cd /data/shared/code && \
        git clone https://github.com/Dao-AILab/flash-attention.git && \
        cd flash-attention && \
        python setup.py install && \
        cd /data/shared/Qwen && \
        rm -rf /data/shared/code/flash-attention; \
    fi

ARG BUNDLE_VLLM=true

# 编译 vllm
RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/pip \
    if [ "$BUNDLE_VLLM" = "true" ]; then \
        mkdir -p /data/shared/code && \
        cd /data/shared/code && \
        git clone -b qwen2_omni_public_v1 https://github.com/fyabc/vllm.git && \
        cd vllm && \
        python3 use_existing_torch.py && \
        pip3 install setuptools_scm && \
        pip3 install -r requirements/cuda.txt && \
        pip3 install . --no-build-isolation && \
        cd /data/shared/Qwen && \
        rm -rf /data/shared/code/vllm; \
    fi

# 安装音视频相关库
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install \
        gradio==5.21.0 \
        gradio_client==1.7.2 \
        librosa==0.11.0 \
        ffmpeg==1.4 \
        ffmpeg-python==0.2.0 \
        soundfile==0.13.1 \
        av

RUN rm -rvf /root/.cache/pip

COPY ./web_demo.py ./

EXPOSE 80
