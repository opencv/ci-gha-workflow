#!/bin/bash
# Builds docker image using selected Dockerfile
# Automatically tags it with iamgename and version found in the file header
# Example:
#   ./build.sh riscv/Dockerfile-main

set -eu

if [ "$#" -ne 1 ]; then
    echo "Error: script requires exactly one argument."
    exit 1
fi

DOCKERFILE=$1

if [ ! -f "${DOCKERFILE}" ]; then
  echo "File ${DOCKERFILE} does not exist!"
  exit 1
fi


IMAGE_NAME=$(grep "# Image name:" ${DOCKERFILE} | sed 's/# Image name: //')
IMAGE_VERSION=$(grep "# Version:" ${DOCKERFILE} | sed 's/# Version: //')

if [ -z "${IMAGE_NAME}" ]; then
  echo "Image name not found in the file header!"
  exit 1
fi

if [ -z "${IMAGE_VERSION}" ]; then
  echo "Version not found in the file header!"
  exit 1
fi

echo "Context   : $(pwd)"
echo "Dockerfile: ${DOCKERFILE}"
echo "Image     : ${IMAGE_NAME}:${IMAGE_VERSION}"

docker build \
    -f "${DOCKERFILE}" \
    -t "${IMAGE_NAME}:${IMAGE_VERSION}" \
    .
