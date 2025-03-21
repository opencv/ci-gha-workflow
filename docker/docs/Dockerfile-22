# Version: 20241202
# Image name: quay.io/opencv-ci/opencv-docs-22.04

FROM ubuntu:22.04

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    software-properties-common \
    gpg-agent curl git htop man zip unzip vim wget ncdu mc nano time \
    file \
    && \
  add-apt-repository ppa:git-core/ppa && \
  apt-get install -y --no-install-recommends git && \
  rm -rf /var/lib/apt/lists/*

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    cmake build-essential \
    doxygen-latex graphviz \
    p7zip-full \
    pylint flake8 \
    python3-bs4 \
    && \
  rm -rf /var/lib/apt/lists/*


# Install fresh Doxygen
ARG doxygen_version=doxygen-1.12.0
ARG doxygen_urlbase=https://github.com/doxygen/doxygen/releases/download/Release_1_12_0
ARG doxygen_archive=${doxygen_version}.linux.bin.tar.gz
ARG doxygen_sha1sum=c50fc71ba9b5e431f0f0f21c5dc8559f47f06007
ADD ${doxygen_urlbase}/${doxygen_archive} /opt/
RUN \
  cd /opt \
  && echo "${doxygen_sha1sum} ${doxygen_archive}" | sha1sum -c \
  && tar -xvf ${doxygen_archive} \
  && rm -rf ${doxygen_archive}
ENV PATH=/opt/${doxygen_version}/bin:${PATH}


# GitHub Actions user's UID is 1001
RUN useradd ci -m -s /bin/bash -G users --uid=1001

USER ci

RUN \
  cd $HOME && \
  mkdir opencv opencv_contrib build && \
  git config --global --add safe.directory "*" && \
  git config --global user.email "opencv.ci" && \
  git config --global user.name "opencv.ci" && \
  git config --global pull.rebase false

# Run docker build from the root directory of the repository
COPY scripts/patch_size.py /home/ci/scripts/patch_size.py

ENTRYPOINT bash
