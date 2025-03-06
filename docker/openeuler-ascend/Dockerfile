# Version: 20240220
# Image name: quay.io/opencv-ci/opencv-openeuler-22.03.sp2-ascend310

FROM openeuler/openeuler:22.03-lts-sp2

RUN yum install -y \
    git \
    wget \
    gcc \
    g++ \
    cmake \
    make \
    python-pip \
    python3-devel \
    xorg-x11-server-Xvfb \
    ninja-build \
    libjpeg-devel \
    libpng-devel \
    libtiff-devel \
    openjpeg2-devel \
    LibRaw-devel \
    gtk3-devel

# Install CANN
RUN wget https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/Milan-ASL/Milan-ASL%20V100R001C17SPC701/Ascend-cann-toolkit_8.0.RC1.alpha001_linux-"$(uname -i)".run && \
    chmod +x Ascend-cann-toolkit_8.0.RC1.alpha001_linux-"$(uname -i)".run && \
    ./Ascend-cann-toolkit_8.0.RC1.alpha001_linux-"$(uname -i)".run --quiet --install && \
    rm -f ./Ascend-cann-toolkit_8.0.RC1.alpha001_linux-"$(uname -i)".run

# Install kernels
RUN wget https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/Milan-ASL/Milan-ASL%20V100R001C17SPC701/Ascend-cann-kernels-310p_8.0.RC1.alpha001_linux.run && \
    chmod +x Ascend-cann-kernels-310p_8.0.RC1.alpha001_linux.run && \
    ./Ascend-cann-kernels-310p_8.0.RC1.alpha001_linux.run --quiet --install && \
    rm -f ./Ascend-cann-kernels-310p_8.0.RC1.alpha001_linux.run

# Self-hosted runner UID is 1001, matches user id on host.
RUN groupadd -g 1000 HwHiAiUser && \
    useradd ci -m -s /bin/bash -G users --uid=1001 && \
    usermod -a -G HwHiAiUser ci

USER ci

ENV LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH:/usr/lib64
ENV ASCEND_TOOLKIT_HOME=/usr/local/Ascend/ascend-toolkit/latest
ENV LD_LIBRARY_PATH=${ASCEND_TOOLKIT_HOME}/lib64:${ASCEND_TOOLKIT_HOME}/lib64/plugin/opskernel:${ASCEND_TOOLKIT_HOME}/lib64/plugin/nnengine:${ASCEND_TOOLKIT_HOME}/opp/built-in/op_impl/ai_core/tbe/op_tiling:$LD_LIBRARY_PATH
ENV PYTHONPATH=${ASCEND_TOOLKIT_HOME}/python/site-packages:${ASCEND_TOOLKIT_HOME}/opp/built-in/op_impl/ai_core/tbe:$PYTHONPATH
ENV PATH=${ASCEND_TOOLKIT_HOME}/bin:${ASCEND_TOOLKIT_HOME}/compiler/ccec_compiler/bin:$PATH
ENV ASCEND_AICPU_PATH=${ASCEND_TOOLKIT_HOME}
ENV ASCEND_OPP_PATH=${ASCEND_TOOLKIT_HOME}/opp
ENV TOOLCHAIN_HOME=${ASCEND_TOOLKIT_HOME}/toolkit
ENV ASCEND_HOME_PATH=${ASCEND_TOOLKIT_HOME}

RUN pip install \
    numpy \
    sympy \
    decorator \
    scipy \
    attrs \
    psutil \
    requests

RUN mkdir $HOME/opencv $HOME/opencv_contrib $HOME/build && \
    git config --global --add safe.directory "*" && \
    git config --global user.email "opencv.ci" && \
    git config --global user.name "opencv.ci" && \
    git config --global pull.rebase false

# Run docker build from the root directory of the repository
COPY scripts/warnings-handling.py /home/ci/scripts/warnings-handling.py

WORKDIR /home/ci
