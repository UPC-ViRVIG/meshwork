#!/bin/bash
# docker/entrypoint.sh
# Runtime GPU/CPU detection and environment setup

# Detect GPU availability
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi > /dev/null 2>&1; then
    echo "GPU detected, running with CUDA support"
    export GPU_AVAILABLE=true
    # Keep CUDA_VISIBLE_DEVICES from environment or default to 0
    export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
else
    echo "No GPU detected, running in CPU mode"
    export GPU_AVAILABLE=false
    export CUDA_VISIBLE_DEVICES=-1
fi

# Set runtime environment based on detection
if [ "$GPU_AVAILABLE" = "true" ]; then
    echo "GPU Runtime: CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
else
    echo "CPU Runtime: GPU acceleration disabled"
fi

# Execute the main command
exec "$@"