# Version: 20241031
# Image name: quay.io/opencv-ci/opencv-ubuntu-24.04

FROM ubuntu:24.04

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    software-properties-common \
    curl zip unzip wget rsync mc nano time git file && \
  rm -rf /var/lib/apt/lists/*

# reportlab, svglib, pycairo: https://github.com/opencv/opencv/pull/23363
# libavif: https://github.com/opencv/opencv/pull/23596
# libjxl: https://github.com/opencv/opencv/pull/26379
RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    cmake \
    build-essential \
    ccache \
    ninja-build \
    python3-dev \
    python3-numpy \
    python3-setuptools \
    python3-pip \
    pylint \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff5-dev \
    libopenjp2-7-dev \
    libavif-dev \
    libjxl-dev \
    libgtk-4-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    ant \
    ant-optional \
    default-jdk \
    hdf5-tools \
    libhdf5-dev \
    liblept5 \
    libgdal-dev \
    libgoogle-glog-dev \
    libarmadillo-dev \
    libeigen3-dev \
    libsuitesparse-dev \
    liblapacke-dev \
    libceres-dev \
    libeigen3-dev \
    libopenni2-dev \
    libglfw3-dev \
    lcov \
    xvfb \
    pkg-config \
    && \
  apt-get clean && \
  pip install --break-system-packages requests reportlab svglib pycairo rlPyCairo && pip cache purge

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    libopenni2-dev \
    libdc1394-dev \
    libgphoto2-dev \
    && \
  rm -rf /var/lib/apt/lists/*

# Self-hosted runner UID is 1000

USER ubuntu

RUN \
  mkdir $HOME/opencv $HOME/opencv_contrib $HOME/build && \
  git config --global --add safe.directory "*" && \
  git config --global user.email "opencv.ci" && \
  git config --global user.name "opencv.ci" && \
  git config --global pull.rebase false

# Run docker build from the root directory of the repository
COPY scripts/warnings-handling.py /home/ubuntu/scripts/warnings-handling.py

CMD bash
