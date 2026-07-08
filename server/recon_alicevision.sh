#!/bin/bash
# server/recon_alicevision.sh
# Enhanced AliceVision GPU reconstruction pipeline

set -e

# Default quality parameters - Feature Extraction
DEFAULT_FEATURE_DENSITY="normal"
DEFAULT_MAX_FEATURES_PER_IMAGE=8000
DEFAULT_CONTRAST_FILTERING="Static"

# Default quality parameters - Image Matching
DEFAULT_MAX_MATCHING_NEIGHBORS=50
DEFAULT_NB_MATCHES_PER_IMAGE=50

# Default quality parameters - Feature Matching
DEFAULT_GEOMETRIC_ERROR_THRESHOLD=0.0
DEFAULT_DISTANCE_RATIO=0.8

# Default quality parameters - SfM Reconstruction
DEFAULT_MAX_REPROJECTION_ERROR=4.0

# Default quality parameters - Dense Reconstruction
DEFAULT_DEPTH_DOWNSCALE=4
DEFAULT_MAX_TCAMS=10
DEFAULT_MIN_VIEW_ANGLE=2.0
DEFAULT_MAX_VIEW_ANGLE=70.0

# Default quality parameters - Mesh Generation
DEFAULT_MAX_INPUT_POINTS=5000000

# Default quality parameters - Texture Mapping
DEFAULT_TEXTURE_SIZE=4096
DEFAULT_TEXTURE_DOWNSCALE=4

# Default pipeline control
DEFAULT_OUTPUT_TYPE="point_cloud"

# Initialize parameters with defaults
FEATURE_DENSITY=$DEFAULT_FEATURE_DENSITY
MAX_FEATURES_PER_IMAGE=$DEFAULT_MAX_FEATURES_PER_IMAGE
CONTRAST_FILTERING=$DEFAULT_CONTRAST_FILTERING
MAX_MATCHING_NEIGHBORS=$DEFAULT_MAX_MATCHING_NEIGHBORS
NB_MATCHES_PER_IMAGE=$DEFAULT_NB_MATCHES_PER_IMAGE
GEOMETRIC_ERROR_THRESHOLD=$DEFAULT_GEOMETRIC_ERROR_THRESHOLD
DISTANCE_RATIO=$DEFAULT_DISTANCE_RATIO
MAX_REPROJECTION_ERROR=$DEFAULT_MAX_REPROJECTION_ERROR
DEPTH_DOWNSCALE=$DEFAULT_DEPTH_DOWNSCALE
MAX_TCAMS=$DEFAULT_MAX_TCAMS
MIN_VIEW_ANGLE=$DEFAULT_MIN_VIEW_ANGLE
MAX_VIEW_ANGLE=$DEFAULT_MAX_VIEW_ANGLE
MAX_INPUT_POINTS=$DEFAULT_MAX_INPUT_POINTS
TEXTURE_SIZE=$DEFAULT_TEXTURE_SIZE
TEXTURE_DOWNSCALE=$DEFAULT_TEXTURE_DOWNSCALE
OUTPUT_TYPE=$DEFAULT_OUTPUT_TYPE
WORKSPACE=""

log() {
    echo "[RECON] $1"
}

log_success() {
    echo "[RECON OK] $1"
}

log_warning() {
    echo "[RECON WARN] $1"
}

log_error() {
    echo "[RECON ERR] $1"
}

show_help() {
    cat << EOF
Enhanced AliceVision GPU reconstruction pipeline

USAGE:
    recon_alicevision.sh --workspace PATH [OPTIONS]

REQUIRED:
    --workspace PATH                    Workspace directory

FEATURE EXTRACTION:
    --feature-density LEVEL             Feature density: low|normal|high|ultra (default: $DEFAULT_FEATURE_DENSITY)
    --max-features-per-image COUNT      Max features per image: 1000-20000 (default: $DEFAULT_MAX_FEATURES_PER_IMAGE)
    --contrast-filtering TYPE           Contrast filtering: Static|AdaptiveToMedianVariance (default: $DEFAULT_CONTRAST_FILTERING)

IMAGE MATCHING:
    --max-matching-neighbors COUNT      Max matching neighbors: 10-100 (default: $DEFAULT_MAX_MATCHING_NEIGHBORS)
    --nb-matches-per-image COUNT        Matches per image: 20-200 (default: $DEFAULT_NB_MATCHES_PER_IMAGE)

FEATURE MATCHING:
    --geometric-error-threshold PIXELS  Geometric error threshold: 0.5-5.0 or 0 for auto (default: $DEFAULT_GEOMETRIC_ERROR_THRESHOLD)
    --distance-ratio RATIO              Distance ratio threshold: 0.6-0.9 (default: $DEFAULT_DISTANCE_RATIO)

SFM RECONSTRUCTION:
    --max-reprojection-error PIXELS     Max reprojection error: 2.0-8.0 (default: $DEFAULT_MAX_REPROJECTION_ERROR)

DENSE RECONSTRUCTION:
    --depth-downscale FACTOR            Depth downscale factor: 1-8 (default: $DEFAULT_DEPTH_DOWNSCALE)
    --max-tcams COUNT                   Max T cameras: 4-20 (default: $DEFAULT_MAX_TCAMS)
    --min-view-angle DEGREES            Min view angle: 0.5-10.0 (default: $DEFAULT_MIN_VIEW_ANGLE)
    --max-view-angle DEGREES            Max view angle: 30.0-89.0 (default: $DEFAULT_MAX_VIEW_ANGLE)

MESH GENERATION:
    --max-input-points COUNT            Max input points: 1M-50M (default: $DEFAULT_MAX_INPUT_POINTS)

TEXTURE MAPPING:
    --texture-size PIXELS               Texture size: 1024-8192 (default: $DEFAULT_TEXTURE_SIZE)
    --texture-downscale FACTOR          Texture downscale: 1-8 (default: $DEFAULT_TEXTURE_DOWNSCALE)

PIPELINE CONTROL:
    --output-type TYPE                  Output type: point_cloud|dense_mesh (default: $DEFAULT_OUTPUT_TYPE)

SYSTEM OPTIONS:
    --help, -h                          Show this help message

EXAMPLES:
    # Low quality (fast preview)
    recon_alicevision.sh --workspace /workspace/project1 --feature-density low --max-features-per-image 4000 --depth-downscale 6

    # Normal quality
    recon_alicevision.sh --workspace /workspace/project1 --output-type dense_mesh

    # High quality
    recon_alicevision.sh --workspace /workspace/project1 --output-type dense_mesh --feature-density high --max-features-per-image 15000 --depth-downscale 2 --texture-size 8192

REQUIREMENTS:
    - GPU with at least 4GB VRAM
    - Input images in workspace/converted/
    - CUDA environment properly configured

WORKSPACE STRUCTURE:
    workspace/converted/        Input images (must exist)
    workspace/tmp/             Intermediate files (created)
    workspace/result/          Final outputs (created)

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --workspace)
                WORKSPACE="$2"
                shift 2
                ;;
            --feature-density)
                FEATURE_DENSITY="$2"
                shift 2
                ;;
            --max-features-per-image)
                MAX_FEATURES_PER_IMAGE="$2"
                shift 2
                ;;
            --contrast-filtering)
                CONTRAST_FILTERING="$2"
                shift 2
                ;;
            --max-matching-neighbors)
                MAX_MATCHING_NEIGHBORS="$2"
                shift 2
                ;;
            --nb-matches-per-image)
                NB_MATCHES_PER_IMAGE="$2"
                shift 2
                ;;
            --geometric-error-threshold)
                GEOMETRIC_ERROR_THRESHOLD="$2"
                shift 2
                ;;
            --distance-ratio)
                DISTANCE_RATIO="$2"
                shift 2
                ;;
            --max-reprojection-error)
                MAX_REPROJECTION_ERROR="$2"
                shift 2
                ;;
            --depth-downscale)
                DEPTH_DOWNSCALE="$2"
                shift 2
                ;;
            --max-tcams)
                MAX_TCAMS="$2"
                shift 2
                ;;
            --min-view-angle)
                MIN_VIEW_ANGLE="$2"
                shift 2
                ;;
            --max-view-angle)
                MAX_VIEW_ANGLE="$2"
                shift 2
                ;;
            --max-input-points)
                MAX_INPUT_POINTS="$2"
                shift 2
                ;;
            --texture-size)
                TEXTURE_SIZE="$2"
                shift 2
                ;;
            --texture-downscale)
                TEXTURE_DOWNSCALE="$2"
                shift 2
                ;;
            --output-type)
                OUTPUT_TYPE="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

validate_parameters() {
    if [ -z "$WORKSPACE" ]; then
        log_error "Workspace is required"
        show_help
        exit 1
    fi

    if [ ! -d "$WORKSPACE" ]; then
        log_error "Workspace directory does not exist: $WORKSPACE"
        exit 1
    fi

    if [ ! -d "$WORKSPACE/converted" ]; then
        log_error "Input directory does not exist: $WORKSPACE/converted"
        exit 1
    fi

    # Validate feature-density
    if [[ "$FEATURE_DENSITY" != "low" && "$FEATURE_DENSITY" != "normal" && "$FEATURE_DENSITY" != "high" && "$FEATURE_DENSITY" != "ultra" ]]; then
        log_error "Invalid feature-density: $FEATURE_DENSITY (must be low|normal|high|ultra)"
        exit 1
    fi

    # Validate max-features-per-image
    if ! [[ "$MAX_FEATURES_PER_IMAGE" =~ ^[0-9]+$ ]] || [ "$MAX_FEATURES_PER_IMAGE" -lt 1000 ] || [ "$MAX_FEATURES_PER_IMAGE" -gt 20000 ]; then
        log_error "Invalid max-features-per-image: $MAX_FEATURES_PER_IMAGE (must be 1000-20000)"
        exit 1
    fi

    # Validate contrast-filtering
    if [[ "$CONTRAST_FILTERING" != "Static" && "$CONTRAST_FILTERING" != "AdaptiveToMedianVariance" ]]; then
        log_error "Invalid contrast-filtering: $CONTRAST_FILTERING (must be Static|AdaptiveToMedianVariance)"
        exit 1
    fi

    # Validate max-matching-neighbors
    if ! [[ "$MAX_MATCHING_NEIGHBORS" =~ ^[0-9]+$ ]] || [ "$MAX_MATCHING_NEIGHBORS" -lt 10 ] || [ "$MAX_MATCHING_NEIGHBORS" -gt 100 ]; then
        log_error "Invalid max-matching-neighbors: $MAX_MATCHING_NEIGHBORS (must be 10-100)"
        exit 1
    fi

    # Validate nb-matches-per-image
    if ! [[ "$NB_MATCHES_PER_IMAGE" =~ ^[0-9]+$ ]] || [ "$NB_MATCHES_PER_IMAGE" -lt 20 ] || [ "$NB_MATCHES_PER_IMAGE" -gt 200 ]; then
        log_error "Invalid nb-matches-per-image: $NB_MATCHES_PER_IMAGE (must be 20-200)"
        exit 1
    fi

    # Validate geometric-error-threshold
    if ! [[ "$GEOMETRIC_ERROR_THRESHOLD" =~ ^[0-9]+\.?[0-9]*$ ]]; then
        log_error "Invalid geometric-error-threshold: $GEOMETRIC_ERROR_THRESHOLD (must be numeric)"
        exit 1
    fi
    if [ "$GEOMETRIC_ERROR_THRESHOLD" != "0" ] && (( $(echo "$GEOMETRIC_ERROR_THRESHOLD < 0.5 || $GEOMETRIC_ERROR_THRESHOLD > 5.0" | bc -l) )); then
        log_error "Invalid geometric-error-threshold: $GEOMETRIC_ERROR_THRESHOLD (must be 0 for auto or 0.5-5.0)"
        exit 1
    fi

    # Validate distance-ratio
    if ! [[ "$DISTANCE_RATIO" =~ ^[0-9]+\.?[0-9]*$ ]] || (( $(echo "$DISTANCE_RATIO < 0.6 || $DISTANCE_RATIO > 0.9" | bc -l) )); then
        log_error "Invalid distance-ratio: $DISTANCE_RATIO (must be 0.6-0.9)"
        exit 1
    fi

    # Validate max-reprojection-error
    if ! [[ "$MAX_REPROJECTION_ERROR" =~ ^[0-9]+\.?[0-9]*$ ]] || (( $(echo "$MAX_REPROJECTION_ERROR < 2.0 || $MAX_REPROJECTION_ERROR > 8.0" | bc -l) )); then
        log_error "Invalid max-reprojection-error: $MAX_REPROJECTION_ERROR (must be 2.0-8.0)"
        exit 1
    fi

    # Validate depth-downscale
    if ! [[ "$DEPTH_DOWNSCALE" =~ ^[0-9]+$ ]] || [ "$DEPTH_DOWNSCALE" -lt 1 ] || [ "$DEPTH_DOWNSCALE" -gt 8 ]; then
        log_error "Invalid depth-downscale: $DEPTH_DOWNSCALE (must be 1-8)"
        exit 1
    fi

    # Validate max-tcams
    if ! [[ "$MAX_TCAMS" =~ ^[0-9]+$ ]] || [ "$MAX_TCAMS" -lt 4 ] || [ "$MAX_TCAMS" -gt 20 ]; then
        log_error "Invalid max-tcams: $MAX_TCAMS (must be 4-20)"
        exit 1
    fi

    # Validate view angles
    if ! [[ "$MIN_VIEW_ANGLE" =~ ^[0-9]+\.?[0-9]*$ ]] || (( $(echo "$MIN_VIEW_ANGLE < 0.5 || $MIN_VIEW_ANGLE > 10.0" | bc -l) )); then
        log_error "Invalid min-view-angle: $MIN_VIEW_ANGLE (must be 0.5-10.0)"
        exit 1
    fi

    if ! [[ "$MAX_VIEW_ANGLE" =~ ^[0-9]+\.?[0-9]*$ ]] || (( $(echo "$MAX_VIEW_ANGLE < 30.0 || $MAX_VIEW_ANGLE > 89.0" | bc -l) )); then
        log_error "Invalid max-view-angle: $MAX_VIEW_ANGLE (must be 30.0-89.0)"
        exit 1
    fi

    if (( $(echo "$MIN_VIEW_ANGLE >= $MAX_VIEW_ANGLE" | bc -l) )); then
        log_error "min-view-angle must be less than max-view-angle"
        exit 1
    fi

    # Validate max-input-points
    if ! [[ "$MAX_INPUT_POINTS" =~ ^[0-9]+$ ]] || [ "$MAX_INPUT_POINTS" -lt 1000000 ] || [ "$MAX_INPUT_POINTS" -gt 50000000 ]; then
        log_error "Invalid max-input-points: $MAX_INPUT_POINTS (must be 1000000-50000000)"
        exit 1
    fi

    # Validate texture-size
    if ! [[ "$TEXTURE_SIZE" =~ ^[0-9]+$ ]] || [ "$TEXTURE_SIZE" -lt 1024 ] || [ "$TEXTURE_SIZE" -gt 8192 ]; then
        log_error "Invalid texture-size: $TEXTURE_SIZE (must be 1024-8192)"
        exit 1
    fi

    # Check if texture size is power of 2
    if (( TEXTURE_SIZE & (TEXTURE_SIZE - 1) )); then
        log_error "texture-size must be power of 2 (1024, 2048, 4096, 8192)"
        exit 1
    fi

    # Validate texture-downscale
    if ! [[ "$TEXTURE_DOWNSCALE" =~ ^[0-9]+$ ]] || [ "$TEXTURE_DOWNSCALE" -lt 1 ] || [ "$TEXTURE_DOWNSCALE" -gt 8 ]; then
        log_error "Invalid texture-downscale: $TEXTURE_DOWNSCALE (must be 1-8)"
        exit 1
    fi

    # Validate output type
    if [[ "$OUTPUT_TYPE" != "point_cloud" && "$OUTPUT_TYPE" != "dense_mesh" ]]; then
        log_error "Invalid output-type: $OUTPUT_TYPE (must be point_cloud or dense_mesh)"
        exit 1
    fi
}

check_gpu_requirements() {
    log "Checking GPU requirements"

    # Check nvidia-smi availability
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        log_error "nvidia-smi not found. GPU is required for AliceVision reconstruction"
        exit 1
    fi

    # Check GPU availability
    if ! nvidia-smi > /dev/null 2>&1; then
        log_error "No GPU detected or driver issue. GPU is required for AliceVision reconstruction"
        exit 1
    fi

    # Check GPU memory (at least 4GB)
    gpu_memory=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
    if [ -z "$gpu_memory" ] || [ "$gpu_memory" -lt 4096 ]; then
        log_error "GPU memory insufficient. At least 4GB VRAM required, found: ${gpu_memory}MB"
        exit 1
    fi

    # Check CUDA environment
    if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
        log_warning "CUDA_VISIBLE_DEVICES not set, using default GPU"
    fi

    log_success "GPU requirements met: ${gpu_memory}MB VRAM available"
}

start_timer() {
    timer_start=$(date +%s)
}

end_timer() {
    timer_end=$(date +%s)
    elapsed=$((timer_end - timer_start))
    echo "Duration: ${elapsed}s"
}

check_workspace() {
    log "Checking workspace: $WORKSPACE"

    image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" -o -iname "*.cr2" -o -iname "*.nef" -o -iname "*.arw" -o -iname "*.dng" -o -iname "*.raw" \) | wc -l)

    if [ "$image_count" -eq 0 ]; then
        log_error "No images found in converted directory: $WORKSPACE/converted"
        exit 1
    fi

    # Create standardized tmp structure
    mkdir -p "$WORKSPACE/tmp"/{01_cameras,02_features,03_matches,04_sfm,05_dense,06_mesh}
    mkdir -p "$WORKSPACE/result"

    log_success "Workspace validated: $image_count images found"
}

camera_initialization() {
    log "Camera initialization"
    start_timer

    cmd="aliceVision_cameraInit \
        --imageFolder \"$WORKSPACE/converted\" \
        --sensorDatabase \"${ALICEVISION_ROOT}/share/aliceVision/cameraSensors.db\" \
        --output \"$WORKSPACE/tmp/01_cameras/cameraInit.sfm\" \
        --defaultFieldOfView 45.0 \
        --allowSingleView 1 \
        --verboseLevel info"
    log "Command: $cmd"
    eval $cmd

    if [ $? -eq 0 ] && [ -f "$WORKSPACE/tmp/01_cameras/cameraInit.sfm" ]; then
        end_timer
        log_success "Camera initialization completed"
    else
        log_error "Camera initialization failed"
        exit 1
    fi
}

feature_extraction() {
    log "Feature extraction"
    log "Parameters: feature-density=$FEATURE_DENSITY, max-features=$MAX_FEATURES_PER_IMAGE, contrast-filtering=$CONTRAST_FILTERING"
    start_timer

    cmd="aliceVision_featureExtraction \
        --input \"$WORKSPACE/tmp/01_cameras/cameraInit.sfm\" \
        --output \"$WORKSPACE/tmp/02_features\" \
        --describerTypes sift \
        --describerPreset $FEATURE_DENSITY \
        --maxNbFeatures $MAX_FEATURES_PER_IMAGE \
        --contrastFiltering $CONTRAST_FILTERING \
        --verboseLevel info"
    log "Command: $cmd"
    eval $cmd

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Feature extraction completed"
    else
        log_error "Feature extraction failed"
        exit 1
    fi
}

image_matching() {
    log "Image matching"
    log "Parameters: max-neighbors=$MAX_MATCHING_NEIGHBORS, matches-per-image=$NB_MATCHES_PER_IMAGE"
    start_timer

    cmd="aliceVision_imageMatching \
        --input \"$WORKSPACE/tmp/01_cameras/cameraInit.sfm\" \
        --featuresFolders \"$WORKSPACE/tmp/02_features\" \
        --output \"$WORKSPACE/tmp/03_matches/imageMatches.txt\" \
        --tree \"$WORKSPACE/tmp/03_matches/tree.txt\" \
        --maxDescriptors $MAX_MATCHING_NEIGHBORS \
        --nbMatches $NB_MATCHES_PER_IMAGE \
        --verboseLevel info"
    log "Command: $cmd"
    eval $cmd

    if [ $? -eq 0 ] && [ -f "$WORKSPACE/tmp/03_matches/imageMatches.txt" ]; then
        end_timer
        log_success "Image matching completed"
    else
        log_error "Image matching failed"
        exit 1
    fi
}

feature_matching() {
    log "Feature matching"
    log "Parameters: geometric-error=$GEOMETRIC_ERROR_THRESHOLD, distance-ratio=$DISTANCE_RATIO"
    start_timer

    # Build command with conditional geometric error
    match_cmd="aliceVision_featureMatching \
        --input \"$WORKSPACE/tmp/01_cameras/cameraInit.sfm\" \
        --featuresFolders \"$WORKSPACE/tmp/02_features\" \
        --imagePairsList \"$WORKSPACE/tmp/03_matches/imageMatches.txt\" \
        --output \"$WORKSPACE/tmp/03_matches\" \
        --describerTypes sift \
        --photometricMatchingMethod ANN_L2 \
        --geometricEstimator acransac \
        --geometricFilterType fundamental_matrix \
        --maxIteration 2048 \
        --distanceRatio $DISTANCE_RATIO \
        --verboseLevel info"

    # Add geometric error if not auto (0)
    if [ "$GEOMETRIC_ERROR_THRESHOLD" != "0" ]; then
        match_cmd="$match_cmd --geometricError $GEOMETRIC_ERROR_THRESHOLD"
    fi

    log "Command: aliceVision_featureMatching --geometricError $GEOMETRIC_ERROR_THRESHOLD --distanceRatio $DISTANCE_RATIO ..."
    eval $match_cmd

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Feature matching completed"
    else
        log_error "Feature matching failed"
        exit 1
    fi
}

structure_from_motion() {
    log "Structure from Motion (SfM)"
    log "Parameters: max-reprojection-error=$MAX_REPROJECTION_ERROR"
    start_timer

    cmd="aliceVision_incrementalSfM \
        --input \"$WORKSPACE/tmp/01_cameras/cameraInit.sfm\" \
        --featuresFolders \"$WORKSPACE/tmp/02_features\" \
        --matchesFolders \"$WORKSPACE/tmp/03_matches\" \
        --output \"$WORKSPACE/tmp/04_sfm/sfm.abc\" \
        --outputViewsAndPoses \"$WORKSPACE/tmp/04_sfm/cameras.sfm\" \
        --extraInfoFolder \"$WORKSPACE/tmp/04_sfm\" \
        --maxReprojectionError $MAX_REPROJECTION_ERROR \
        --verboseLevel info"
    log "Command: $cmd"
    eval $cmd

    if [ $? -eq 0 ] && [ -f "$WORKSPACE/tmp/04_sfm/sfm.abc" ]; then
        end_timer
        log_success "Structure from Motion completed"
    else
        log_error "Structure from Motion failed"
        exit 1
    fi
}

prepare_dense_scene() {
    log "Prepare dense scene"
    start_timer

    log "Command: aliceVision_prepareDenseScene ..."
    aliceVision_prepareDenseScene \
        --input "$WORKSPACE/tmp/04_sfm/sfm.abc" \
        --output "$WORKSPACE/tmp/05_dense" \
        --verboseLevel info

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Dense scene preparation completed"
    else
        log_error "Dense scene preparation failed"
        exit 1
    fi
}

depth_map_estimation() {
    log "Depth map estimation"
    log "Parameters: depth-downscale=$DEPTH_DOWNSCALE, max-tcams=$MAX_TCAMS, view-angles=$MIN_VIEW_ANGLE-$MAX_VIEW_ANGLE"
    start_timer

    log "Command: aliceVision_depthMapEstimation --downscale $DEPTH_DOWNSCALE --maxTCams $MAX_TCAMS ..."
    aliceVision_depthMapEstimation \
        --input "$WORKSPACE/tmp/04_sfm/sfm.abc" \
        --imagesFolder "$WORKSPACE/tmp/05_dense" \
        --output "$WORKSPACE/tmp/05_dense" \
        --downscale $DEPTH_DOWNSCALE \
        --minViewAngle $MIN_VIEW_ANGLE \
        --maxViewAngle $MAX_VIEW_ANGLE \
        --maxTCams $MAX_TCAMS \
        --sgmWSH 4 \
        --sgmGammaC 5.0 \
        --sgmGammaP 8.0 \
        --refineMaxTCamsPerTile $(($MAX_TCAMS / 2)) \
        --refineSubsampling 10 \
        --verboseLevel info

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Depth map estimation completed"
    else
        log_error "Depth map estimation failed"
        exit 1
    fi
}

depth_map_filtering() {
    log "Depth map filtering"
    log "Parameters: view-angles=$MIN_VIEW_ANGLE-$MAX_VIEW_ANGLE"
    start_timer

    # Use fixed consistent cameras based on quality settings
    min_consistent_cams=3
    if [ "$FEATURE_DENSITY" = "low" ]; then
        min_consistent_cams=2
    elif [ "$FEATURE_DENSITY" = "high" ] || [ "$FEATURE_DENSITY" = "ultra" ]; then
        min_consistent_cams=4
    fi

    log "Command: aliceVision_depthMapFiltering --minNumOfConsistentCams $min_consistent_cams ..."
    aliceVision_depthMapFiltering \
        --input "$WORKSPACE/tmp/04_sfm/sfm.abc" \
        --depthMapsFolder "$WORKSPACE/tmp/05_dense" \
        --output "$WORKSPACE/tmp/05_dense" \
        --minViewAngle $MIN_VIEW_ANGLE \
        --maxViewAngle $MAX_VIEW_ANGLE \
        --minNumOfConsistentCams $min_consistent_cams \
        --minNumOfConsistentCamsWithLowSimilarity $min_consistent_cams \
        --verboseLevel info

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Depth map filtering completed"
    else
        log_error "Depth map filtering failed"
        exit 1
    fi
}

meshing() {
    log "Meshing"
    log "Parameters: max-input-points=$MAX_INPUT_POINTS, save-raw-dense-cloud=1"
    start_timer

    # Always generate mesh file (required parameter), but log different intentions
    if [ "$OUTPUT_TYPE" = "point_cloud" ]; then
        log "Generating dense point cloud (mesh file created but not used in final output)"
    else
        log "Generating dense point cloud and mesh"
    fi

    cmd="aliceVision_meshing \
        --input \"$WORKSPACE/tmp/04_sfm/sfm.abc\" \
        --depthMapsFolder \"$WORKSPACE/tmp/05_dense\" \
        --output \"$WORKSPACE/tmp/06_mesh/mesh.abc\" \
        --outputMesh \"$WORKSPACE/tmp/06_mesh/mesh.obj\" \
        --maxInputPoints $MAX_INPUT_POINTS \
        --maxPoints $(($MAX_INPUT_POINTS / 2)) \
        --maxPointsPerVoxel 1000000 \
        --minStep 2 \
        --partitioning singleBlock \
        --repartition multiResolution \
        --helperPointsGridSize 10 \
        --saveRawDensePointCloud 1 \
        --verboseLevel info"
    log "Command: $cmd"
    eval $cmd

    if [ $? -eq 0 ] && [ -f "$WORKSPACE/tmp/06_mesh/mesh.abc" ]; then
        end_timer
        log_success "Meshing completed"
    else
        log_error "Meshing failed"
        exit 1
    fi
}

texturing() {
    if [ "$OUTPUT_TYPE" = "point_cloud" ]; then
        return 0
    fi

    log "Texturing"
    log "Parameters: texture-size=$TEXTURE_SIZE, texture-downscale=$TEXTURE_DOWNSCALE"
    start_timer

    input_mesh="$WORKSPACE/tmp/06_mesh/mesh.obj"
    if [ ! -f "$input_mesh" ]; then
        log_error "No mesh found for texturing"
        exit 1
    fi

    log "Command: aliceVision_texturing --textureSide $TEXTURE_SIZE --downscale $TEXTURE_DOWNSCALE ..."
    aliceVision_texturing \
        --input "$WORKSPACE/tmp/06_mesh/mesh.abc" \
        --imagesFolder "$WORKSPACE/tmp/05_dense" \
        --inputMesh "$input_mesh" \
        --output "$WORKSPACE/tmp/06_mesh" \
        --textureSide $TEXTURE_SIZE \
        --downscale $TEXTURE_DOWNSCALE \
        --outputMeshFileType obj \
        --unwrapMethod Basic \
        --useUDIM true \
        --fillHoles false \
        --padding 15 \
        --multiBandDownscale 4 \
        --useScore true \
        --verboseLevel info

    if [ $? -eq 0 ] && [ -f "$WORKSPACE/tmp/06_mesh/texturedMesh.obj" ]; then
        end_timer
        log_success "Texturing completed"
    else
        log_error "Texturing failed"
        exit 1
    fi
}

export_cloud() {
    log "Exporting point cloud files"

    # Export camera parameters
    if [ -f "$WORKSPACE/tmp/04_sfm/cameras.sfm" ]; then
        cp "$WORKSPACE/tmp/04_sfm/cameras.sfm" "$WORKSPACE/result/cameras.sfm"
        log_success "Exported camera parameters"
    fi

    # Export sparse point cloud (both ABC and PLY formats)
    if [ -f "$WORKSPACE/tmp/04_sfm/sfm.abc" ]; then
        # Copy original ABC format
        cp "$WORKSPACE/tmp/04_sfm/sfm.abc" "$WORKSPACE/result/sparse_points.abc"
        log_success "Exported sparse points ABC format"

        # Generate colored PLY format (two-step process)
        log "Generating colored sparse point cloud PLY..."

        cmd1="aliceVision_exportColoredPointCloud \
            --input \"$WORKSPACE/tmp/04_sfm/sfm.abc\" \
            --output \"$WORKSPACE/result/colored_sparse.abc\" \
            --verboseLevel info"
        log "Command: $cmd1"
        eval $cmd1 2>/dev/null

        if [ -f "$WORKSPACE/result/colored_sparse.abc" ]; then
            cmd2="aliceVision_convertSfMFormat \
                --input \"$WORKSPACE/result/colored_sparse.abc\" \
                --output \"$WORKSPACE/result/sparse_points.ply\" \
                --describerTypes sift \
                --structure 1 --observations 0 --views 0 --intrinsics 0 --extrinsics 0 \
                --verboseLevel info"
            log "Command: $cmd2"
            eval $cmd2 2>/dev/null

            if [ -f "$WORKSPACE/result/sparse_points.ply" ]; then
                log_success "Exported sparse points PLY format with colors"
            else
                log_warning "PLY export failed, ABC format available"
            fi

            # Cleanup temporary file
            rm -f "$WORKSPACE/result/colored_sparse.abc"
        else
            log_warning "Color export failed, ABC format available"
        fi
    fi

    # Export dense point cloud (both ABC and PLY formats)
    dense_files=("$WORKSPACE/tmp/06_mesh/mesh.abc"
                 "$WORKSPACE/tmp/06_mesh/densePointCloud_raw.abc"
                 "$WORKSPACE/tmp/06_mesh/densePointCloud.abc")

    dense_exported=false
    for dense_file in "${dense_files[@]}"; do
        if [ -f "$dense_file" ]; then
            log "Found dense point cloud: $(basename $dense_file)"

            # Copy original ABC format
            cp "$dense_file" "$WORKSPACE/result/dense_points.abc"
            log_success "Exported dense points ABC format"

            # Generate colored PLY format (two-step process)
            log "Generating colored dense point cloud PLY..."

            cmd1="aliceVision_exportColoredPointCloud \
                --input \"$dense_file\" \
                --output \"$WORKSPACE/result/colored_dense.abc\" \
                --verboseLevel info"
            log "Command: $cmd1"
            eval $cmd1 2>/dev/null

            if [ -f "$WORKSPACE/result/colored_dense.abc" ]; then
                cmd2="aliceVision_convertSfMFormat \
                    --input \"$WORKSPACE/result/colored_dense.abc\" \
                    --output \"$WORKSPACE/result/dense_points.ply\" \
                    --describerTypes unknown \
                    --structure 1 --observations 0 --views 0 --intrinsics 0 --extrinsics 0 \
                    --verboseLevel info"
                log "Command: $cmd2"
                eval $cmd2 2>/dev/null

                if [ -f "$WORKSPACE/result/dense_points.ply" ]; then
                    log_success "Exported dense points PLY format with colors"
                else
                    log_warning "PLY export failed, ABC format available"
                fi

                # Cleanup temporary file
                rm -f "$WORKSPACE/result/colored_dense.abc"
            else
                log_warning "Color export failed, ABC format available"
            fi

            dense_exported=true
            break
        fi
    done

    if [ "$dense_exported" = false ]; then
        log_warning "No dense point cloud found in meshing output"
    fi

    log_success "Point cloud export completed"
}

validate_color_data() {
    local ply_file="$1"
    local stage="$2"

    if [ ! -f "$ply_file" ]; then
        log_warning "PLY file not found for validation: $ply_file"
        return 1
    fi

    local has_colors=0
    local color_check=$(head -20 "$ply_file" | grep -i "property.*red\|property.*green\|property.*blue" | wc -l)

    if [ "$color_check" -ge 3 ]; then
        has_colors=1
    fi

    local file_size=$(stat -f%z "$ply_file" 2>/dev/null || stat -c%s "$ply_file" 2>/dev/null)
    local size_mb=$((file_size / 1024 / 1024))

    if [ $has_colors -eq 1 ]; then
        log_success "$stage validation: colors present (${size_mb}MB)"
        return 0
    else
        log_warning "$stage validation: no colors detected (${size_mb}MB)"
        return 1
    fi
}

organize_results() {
    log "Organizing results to result directory"

    local result_dir="$WORKSPACE/result"
    local timestamp=$(date '+%Y%m%d_%H%M%S')

    # Copy camera parameters
    if [ -f "$WORKSPACE/tmp/04_sfm/cameras.sfm" ]; then
        cp "$WORKSPACE/tmp/04_sfm/cameras.sfm" "$result_dir/cameras.sfm"
        log_success "Copied camera parameters"
    fi

    # Validate point cloud files
    for cloud_file in "$result_dir"/sparse_points.* "$result_dir"/dense_points.*; do
        if [ -f "$cloud_file" ]; then
            filename=$(basename "$cloud_file")
            if [[ "$filename" == *.ply ]]; then
                validate_color_data "$cloud_file" "point cloud"
            else
                log_success "Point cloud exported: $filename"
            fi
        fi
    done

    # Copy mesh results for dense_mesh output
    if [ "$OUTPUT_TYPE" = "dense_mesh" ]; then
        if [ -f "$WORKSPACE/tmp/06_mesh/texturedMesh.obj" ]; then
            cp "$WORKSPACE/tmp/06_mesh/texturedMesh.obj" "$result_dir/textured_mesh.obj"
            log_success "Copied textured mesh (OBJ)"
        fi

        if [ -f "$WORKSPACE/tmp/06_mesh/texturedMesh.mtl" ]; then
            cp "$WORKSPACE/tmp/06_mesh/texturedMesh.mtl" "$result_dir/textured_mesh.mtl"
            log_success "Copied material file (MTL)"
        fi

        # Copy texture files
        for texture_file in "$WORKSPACE/tmp/06_mesh"/*.jpg; do
            if [ -f "$texture_file" ]; then
                texture_name=$(basename "$texture_file")
                cp "$texture_file" "$result_dir/$texture_name"
                log_success "Copied texture: $texture_name"
            fi
        done
    fi

    generate_metadata "$result_dir" "$timestamp"
    log_success "Results organized in: $result_dir"
}

generate_metadata() {
    local result_dir="$1"
    local timestamp="$2"
    local metadata_file="$result_dir/reconstruction.json"

    local image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" \) | wc -l)

    cat > "$metadata_file" << EOF
{
  "reconstruction_info": {
    "timestamp": "$timestamp",
    "workspace": "$WORKSPACE",
    "output_type": "$OUTPUT_TYPE",
    "parameters": {
      "feature_density": "$FEATURE_DENSITY",
      "max_features_per_image": $MAX_FEATURES_PER_IMAGE,
      "contrast_filtering": "$CONTRAST_FILTERING",
      "max_matching_neighbors": $MAX_MATCHING_NEIGHBORS,
      "nb_matches_per_image": $NB_MATCHES_PER_IMAGE,
      "geometric_error_threshold": $GEOMETRIC_ERROR_THRESHOLD,
      "distance_ratio": $DISTANCE_RATIO,
      "max_reprojection_error": $MAX_REPROJECTION_ERROR,
      "depth_downscale": $DEPTH_DOWNSCALE,
      "max_tcams": $MAX_TCAMS,
      "min_view_angle": $MIN_VIEW_ANGLE,
      "max_view_angle": $MAX_VIEW_ANGLE,
      "max_input_points": $MAX_INPUT_POINTS,
      "texture_size": $TEXTURE_SIZE,
      "texture_downscale": $TEXTURE_DOWNSCALE
    }
  },
  "statistics": {
    "input_images": $image_count
  },
  "output_files": {
    "cameras": "cameras.sfm",
    "sparse_points": "sparse_points.ply or sparse_points.abc",
    "dense_points": "dense_points.ply or dense_points.abc",
    "textured_mesh": "textured_mesh.obj",
    "material_file": "textured_mesh.mtl"
  }
}
EOF

    log_success "Generated metadata: reconstruction.json"
}

run_reconstruction_pipeline() {
    log "Running AliceVision reconstruction pipeline (output type: $OUTPUT_TYPE)"

    check_gpu_requirements
    check_workspace
    camera_initialization
    feature_extraction
    image_matching
    feature_matching
    structure_from_motion
    prepare_dense_scene
    depth_map_estimation
    depth_map_filtering
    meshing

    if [ "$OUTPUT_TYPE" = "dense_mesh" ]; then
        texturing
    fi

    export_cloud
    organize_results

    log_success "AliceVision reconstruction pipeline completed successfully"
    return 0
}

generate_report() {
    log "Generating reconstruction report"

    echo
    echo "============================================"
    echo "Enhanced AliceVision GPU Reconstruction Report"
    echo "============================================"
    echo "Workspace: $WORKSPACE"
    echo "Output type: $OUTPUT_TYPE"
    echo "Feature density: $FEATURE_DENSITY"
    echo "Max features per image: $MAX_FEATURES_PER_IMAGE"
    echo "Contrast filtering: $CONTRAST_FILTERING"
    echo "Max matching neighbors: $MAX_MATCHING_NEIGHBORS"
    echo "Matches per image: $NB_MATCHES_PER_IMAGE"
    echo "Geometric error threshold: $GEOMETRIC_ERROR_THRESHOLD"
    echo "Distance ratio: $DISTANCE_RATIO"
    echo "Max reprojection error: $MAX_REPROJECTION_ERROR"
    echo "Depth downscale: $DEPTH_DOWNSCALE"
    echo "Max T-cams: $MAX_TCAMS"
    echo "View angle range: $MIN_VIEW_ANGLE - $MAX_VIEW_ANGLE degrees"

    if [ "$OUTPUT_TYPE" = "dense_mesh" ]; then
        echo "Max input points: $MAX_INPUT_POINTS"
        echo "Texture size: $TEXTURE_SIZE"
        echo "Texture downscale: $TEXTURE_DOWNSCALE"
    fi
    echo

    local image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" \) | wc -l)
    echo "Input images: $image_count"

    echo
    echo "Final outputs in result directory:"
    for output_file in "$WORKSPACE/result"/*.obj "$WORKSPACE/result"/*.mtl "$WORKSPACE/result"/*.ply "$WORKSPACE/result"/*.sfm "$WORKSPACE/result"/*.json "$WORKSPACE/result"/*.jpg; do
        if [ -f "$output_file" ]; then
            file_size=$(stat -f%z "$output_file" 2>/dev/null || stat -c%s "$output_file" 2>/dev/null)
            if [ "$file_size" -gt 0 ]; then
                file_size_mb=$((file_size / 1024 / 1024))
                filename=$(basename "$output_file")
                echo "  $filename: ${file_size_mb}MB"
            fi
        fi
    done

    echo
    echo "Pipeline: Camera Init -> Feature Extraction -> Matching -> SfM -> Dense Reconstruction"
    if [ "$OUTPUT_TYPE" = "dense_mesh" ]; then
        echo "          -> Meshing -> Texturing"
    fi
    echo "Result location: $WORKSPACE/result"
    echo "============================================"
}

main() {
    overall_start=$(date +%s)

    log "Starting enhanced AliceVision GPU reconstruction pipeline"

    parse_arguments "$@"
    validate_parameters

    log "Parameters: workspace=$WORKSPACE, output-type=$OUTPUT_TYPE"

    run_reconstruction_pipeline
    result=$?

    overall_end=$(date +%s)
    overall_elapsed=$((overall_end - overall_start))
    overall_minutes=$((overall_elapsed / 60))
    overall_seconds=$((overall_elapsed % 60))

    generate_report

    echo
    if [ $result -eq 0 ]; then
        log_success "AliceVision reconstruction pipeline completed successfully"
    else
        log_error "AliceVision reconstruction pipeline failed"
    fi
    log "Total time: ${overall_minutes}m ${overall_seconds}s"

    exit $result
}

main "$@"