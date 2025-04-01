# Version: 20230724
# Image name: quay.io/opencv-ci/opencv-ubuntu-20.04-openvino

FROM openvino/ubuntu20_dev:2024.0.0

USER root

RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    software-properties-common \
    curl zip unzip wget rsync mc nano time \
    file \
    && \
  add-apt-repository ppa:git-core/ppa && \
  apt-get install -y --no-install-recommends git && \
  rm -rf /var/lib/apt/lists/*

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
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff5-dev \
    libopenjp2-7-dev \
    libgtk-3-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libavresample-dev \
    hdf5-tools \
    libhdf5-dev \
    liblept5 \
    libgoogle-glog-dev \
    libatlas-base-dev \
    libeigen3-dev \
    libsuitesparse-dev \
    liblapacke-dev \
    libeigen3-dev \
    xvfb \
    pkg-config \
    && \
  apt-get clean

# The base OpenVINO image has openvino user with UID=1000. Use it by default
USER openvino

RUN \
  mkdir $HOME/opencv $HOME/opencv_contrib $HOME/build && \
  git config --global --add safe.directory "*" && \
  git config --global user.email "opencv.ci" && \
  git config --global user.name "opencv.ci" && \
  git config --global pull.rebase false

# Run docker build from the root directory of the repository
COPY scripts/warnings-handling.py /home/openvino/scripts/warnings-handling.py

# do not use OpenVINO provided pre-built instance of OpenCV
ENV OpenCV_DIR=

CMD bash
