#!/bin/bash
# server/recon_colmap.sh

set -e

MAX_IMAGE_SIZE=1600
MAX_NUM_FEATURES=8192
MAX_NUM_MATCHES=16384
GUIDED_MATCHING=1
MAX_THREADS=0
OPENMVS_RESOLUTION_LEVEL=2
OPENMVS_MAX_RESOLUTION=1600
OPENMVS_NUMBER_VIEWS=3
OUTPUT_TYPE="point_cloud"
WORKSPACE=""
VOCAB_TREE_PATH=""

DENSIFY_ITERS=2
DENSIFY_GEOMETRIC_ITERS=1
DENSIFY_SUB_RESOLUTION_LEVELS=1
DENSIFY_MAX_THREADS=2
REFINE_SCALES=2
REFINE_DECIMATE=0.1
TEXMESH_RESOLUTION_LEVEL=1

MATCHER_TYPE="exhaustive"
MATCHER_THRESHOLD=100

if [ "${GPU_AVAILABLE}" = "true" ]; then
    USE_GPU=1
    CUDA_DEVICE=0
    USE_GPU_BA=1
else
    USE_GPU=0
    CUDA_DEVICE=-2
    USE_GPU_BA=0
fi

log() { echo "[RECON] $1"; }
log_success() { echo "[RECON OK] $1"; }
log_warning() { echo "[RECON WARN] $1"; }
log_error() { echo "[RECON ERR] $1"; }

show_help() {
    cat << EOF
COLMAP + OpenMVS reconstruction pipeline

USAGE:
    recon_colmap.sh --workspace PATH [OPTIONS]

REQUIRED:
    --workspace PATH

COLMAP PARAMETERS:
    --max-image-size PIXELS         (default: 1600)
    --max-features COUNT            (default: 8192)
    --max-num-matches COUNT         (default: 16384)
    --guided-matching 0|1           (default: 1)
    --num-threads COUNT             (default: auto)

OPENMVS DENSIFY PARAMETERS:
    --resolution-level LEVEL        0-4 (default: 2)
    --max-resolution PIXELS         (default: 1600)
    --number-views COUNT            (default: 3)
    --densify-iters COUNT           (default: 2)
    --densify-geometric-iters N     (default: 1)
    --densify-sub-resolution N      (default: 1)
    --densify-max-threads N         (default: 2)

OPENMVS MESH PARAMETERS:
    --refine-scales N               (default: 2)
    --refine-decimate RATIO         (default: 0.1)
    --texmesh-resolution-level N    (default: 1)

PIPELINE CONTROL:
    --output-type TYPE              point_cloud|dense_mesh (default: point_cloud)
    --vocab-tree-path PATH          vocab tree path for large datasets (optional)

SYSTEM OPTIONS:
    --help, -h

GPU CONTROL:
    Set environment variable GPU_AVAILABLE=true to enable GPU acceleration.

EXAMPLES:
    recon_colmap.sh --workspace /workspace/recon_001 --output-type point_cloud
    recon_colmap.sh --workspace /workspace/recon_001 --output-type dense_mesh \\
        --max-image-size 2400 --max-features 16384 --resolution-level 1

EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --workspace)                WORKSPACE="$2"; shift 2 ;;
            --max-image-size)           MAX_IMAGE_SIZE="$2"; shift 2 ;;
            --max-features)             MAX_NUM_FEATURES="$2"; shift 2 ;;
            --max-num-matches)          MAX_NUM_MATCHES="$2"; shift 2 ;;
            --guided-matching)          GUIDED_MATCHING="$2"; shift 2 ;;
            --num-threads)              MAX_THREADS="$2"; shift 2 ;;
            --resolution-level)         OPENMVS_RESOLUTION_LEVEL="$2"; shift 2 ;;
            --max-resolution)           OPENMVS_MAX_RESOLUTION="$2"; shift 2 ;;
            --number-views)             OPENMVS_NUMBER_VIEWS="$2"; shift 2 ;;
            --densify-iters)            DENSIFY_ITERS="$2"; shift 2 ;;
            --densify-geometric-iters)  DENSIFY_GEOMETRIC_ITERS="$2"; shift 2 ;;
            --densify-sub-resolution)   DENSIFY_SUB_RESOLUTION_LEVELS="$2"; shift 2 ;;
            --densify-max-threads)      DENSIFY_MAX_THREADS="$2"; shift 2 ;;
            --refine-scales)            REFINE_SCALES="$2"; shift 2 ;;
            --refine-decimate)          REFINE_DECIMATE="$2"; shift 2 ;;
            --texmesh-resolution-level) TEXMESH_RESOLUTION_LEVEL="$2"; shift 2 ;;
            --output-type)              OUTPUT_TYPE="$2"; shift 2 ;;
            --vocab-tree-path)          VOCAB_TREE_PATH="$2"; shift 2 ;;
            --help|-h)                  show_help; exit 0 ;;
            *)                          log_error "Unknown option: $1"; show_help; exit 1 ;;
        esac
    done
}

detect_environment() {
    if [ "$MAX_THREADS" -eq 0 ] 2>/dev/null; then
        detected=$(nproc 2>/dev/null || echo 4)
        if [ "$detected" -lt 1 ]; then
            detected=4
        fi
        if [ "$detected" -gt 16 ]; then
            MAX_THREADS=16
        else
            MAX_THREADS=$detected
        fi
        log "Auto-detected threads: $MAX_THREADS"
    fi
    log "GPU mode: GPU_AVAILABLE=${GPU_AVAILABLE:-false}, USE_GPU=$USE_GPU, CUDA_DEVICE=$CUDA_DEVICE, USE_GPU_BA=$USE_GPU_BA"
}

validate_parameters() {
    if [ -z "$WORKSPACE" ]; then
        log_error "Workspace is required"; show_help; exit 1
    fi
    if [ ! -d "$WORKSPACE" ]; then
        log_error "Workspace directory does not exist: $WORKSPACE"; exit 1
    fi
    if [ ! -d "$WORKSPACE/converted" ]; then
        log_error "Input directory does not exist: $WORKSPACE/converted"; exit 1
    fi
    if ! [[ "$MAX_IMAGE_SIZE" =~ ^[0-9]+$ ]] || [ "$MAX_IMAGE_SIZE" -lt 512 ] || [ "$MAX_IMAGE_SIZE" -gt 4000 ]; then
        log_error "Invalid max-image-size: $MAX_IMAGE_SIZE (must be 512-4000)"; exit 1
    fi
    if ! [[ "$MAX_NUM_FEATURES" =~ ^[0-9]+$ ]] || [ "$MAX_NUM_FEATURES" -lt 1000 ] || [ "$MAX_NUM_FEATURES" -gt 20000 ]; then
        log_error "Invalid max-features: $MAX_NUM_FEATURES (must be 1000-20000)"; exit 1
    fi
    if ! [[ "$MAX_NUM_MATCHES" =~ ^[0-9]+$ ]] || [ "$MAX_NUM_MATCHES" -lt 1000 ] || [ "$MAX_NUM_MATCHES" -gt 65536 ]; then
        log_error "Invalid max-num-matches: $MAX_NUM_MATCHES (must be 1000-65536)"; exit 1
    fi
    if [[ "$GUIDED_MATCHING" != "0" && "$GUIDED_MATCHING" != "1" ]]; then
        log_error "Invalid guided-matching: $GUIDED_MATCHING (must be 0 or 1)"; exit 1
    fi
    if ! [[ "$MAX_THREADS" =~ ^[0-9]+$ ]] || [ "$MAX_THREADS" -lt 1 ] || [ "$MAX_THREADS" -gt 16 ]; then
        log_error "Invalid num-threads: $MAX_THREADS (must be 1-16)"; exit 1
    fi
    if ! [[ "$OPENMVS_RESOLUTION_LEVEL" =~ ^[0-9]+$ ]] || [ "$OPENMVS_RESOLUTION_LEVEL" -lt 0 ] || [ "$OPENMVS_RESOLUTION_LEVEL" -gt 4 ]; then
        log_error "Invalid resolution-level: $OPENMVS_RESOLUTION_LEVEL (must be 0-4)"; exit 1
    fi
    if ! [[ "$OPENMVS_MAX_RESOLUTION" =~ ^[0-9]+$ ]] || [ "$OPENMVS_MAX_RESOLUTION" -lt 480 ] || [ "$OPENMVS_MAX_RESOLUTION" -gt 4000 ]; then
        log_error "Invalid max-resolution: $OPENMVS_MAX_RESOLUTION (must be 480-4000)"; exit 1
    fi
    if ! [[ "$OPENMVS_NUMBER_VIEWS" =~ ^[0-9]+$ ]] || [ "$OPENMVS_NUMBER_VIEWS" -lt 2 ] || [ "$OPENMVS_NUMBER_VIEWS" -gt 10 ]; then
        log_error "Invalid number-views: $OPENMVS_NUMBER_VIEWS (must be 2-10)"; exit 1
    fi
    if [[ "$OUTPUT_TYPE" != "point_cloud" && "$OUTPUT_TYPE" != "dense_mesh" ]]; then
        log_error "Invalid output-type: $OUTPUT_TYPE (must be point_cloud or dense_mesh)"; exit 1
    fi
    if [ -n "$VOCAB_TREE_PATH" ] && [ ! -f "$VOCAB_TREE_PATH" ]; then
        log_error "Vocab tree file not found: $VOCAB_TREE_PATH"; exit 1
    fi
}

start_timer() { timer_start=$(date +%s); }

end_timer() {
    timer_end=$(date +%s)
    elapsed=$((timer_end - timer_start))
    echo "Duration: ${elapsed}s"
}

check_workspace() {
    log "Checking workspace: $WORKSPACE"

    image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \
        \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" \) | wc -l)

    if [ "$image_count" -eq 0 ]; then
        log_error "No images found in converted directory: $WORKSPACE/converted"; exit 1
    fi

    mkdir -p "$WORKSPACE/tmp"/{sparse,openmvs}
    mkdir -p "$WORKSPACE/result"

    if [ "$image_count" -gt "$MATCHER_THRESHOLD" ] && [ -n "$VOCAB_TREE_PATH" ]; then
        MATCHER_TYPE="vocab_tree"
        log "Matcher: vocab_tree (image_count=$image_count > threshold=$MATCHER_THRESHOLD)"
    else
        MATCHER_TYPE="exhaustive"
        if [ "$image_count" -gt "$MATCHER_THRESHOLD" ] && [ -z "$VOCAB_TREE_PATH" ]; then
            log_warning "image_count=$image_count > $MATCHER_THRESHOLD but no vocab tree path provided, falling back to exhaustive_matcher"
        fi
        log "Matcher: exhaustive (image_count=$image_count)"
    fi

    log_success "Workspace validated: $image_count images found"
}

extract_features() {
    log "Extracting features"
    log "Parameters: size=$MAX_IMAGE_SIZE, features=$MAX_NUM_FEATURES, threads=$MAX_THREADS, gpu=$USE_GPU"

    start_timer

    database_path="$WORKSPACE/tmp/database.db"
    image_path="$WORKSPACE/converted"

    colmap feature_extractor \
        --database_path "$database_path" \
        --image_path "$image_path" \
        --ImageReader.single_camera 1 \
        --ImageReader.camera_model PINHOLE \
        --FeatureExtraction.max_image_size $MAX_IMAGE_SIZE \
        --FeatureExtraction.num_threads $MAX_THREADS \
        --FeatureExtraction.use_gpu $USE_GPU \
        --SiftExtraction.max_num_features $MAX_NUM_FEATURES \
        --SiftExtraction.first_octave -1 \
        --SiftExtraction.num_octaves 4 \
        --SiftExtraction.octave_resolution 3 \
        --SiftExtraction.peak_threshold 0.02 \
        --SiftExtraction.edge_threshold 10.0

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Feature extraction completed"
    else
        log_error "Feature extraction failed"
        exit 1
    fi
}

match_features() {
    log "Matching features (matcher=$MATCHER_TYPE)"
    log "Parameters: guided=$GUIDED_MATCHING, max_matches=$MAX_NUM_MATCHES, gpu=$USE_GPU, threads=$MAX_THREADS"

    start_timer

    database_path="$WORKSPACE/tmp/database.db"

    if [ "$MATCHER_TYPE" = "vocab_tree" ]; then
        colmap vocab_tree_matcher \
            --database_path "$database_path" \
            --FeatureMatching.guided_matching $GUIDED_MATCHING \
            --FeatureMatching.max_num_matches $MAX_NUM_MATCHES \
            --FeatureMatching.use_gpu $USE_GPU \
            --FeatureMatching.num_threads $MAX_THREADS \
            --SiftMatching.cross_check 1 \
            --SiftMatching.max_ratio 0.8 \
            --SiftMatching.max_distance 0.7 \
            --VocabTreeMatching.vocab_tree_path "$VOCAB_TREE_PATH"
    else
        colmap exhaustive_matcher \
            --database_path "$database_path" \
            --FeatureMatching.guided_matching $GUIDED_MATCHING \
            --FeatureMatching.max_num_matches $MAX_NUM_MATCHES \
            --FeatureMatching.use_gpu $USE_GPU \
            --FeatureMatching.num_threads $MAX_THREADS \
            --SiftMatching.cross_check 1 \
            --SiftMatching.max_ratio 0.8 \
            --SiftMatching.max_distance 0.7
    fi

    if [ $? -eq 0 ]; then
        end_timer
        log_success "Feature matching completed"
    else
        log_error "Feature matching failed"
        exit 1
    fi
}

sparse_reconstruction() {
    log "Sparse reconstruction"

    start_timer

    database_path="$WORKSPACE/tmp/database.db"
    image_path="$WORKSPACE/converted"
    output_path="$WORKSPACE/tmp/sparse"

    colmap mapper \
        --database_path "$database_path" \
        --image_path "$image_path" \
        --output_path "$output_path" \
        --Mapper.init_min_num_inliers 50 \
        --Mapper.init_max_error 4.0 \
        --Mapper.init_max_forward_motion 0.95 \
        --Mapper.init_min_tri_angle 16.0 \
        --Mapper.abs_pose_max_error 12.0 \
        --Mapper.abs_pose_min_num_inliers 20 \
        --Mapper.abs_pose_min_inlier_ratio 0.2 \
        --Mapper.ba_local_num_images 6 \
        --Mapper.ba_local_max_num_iterations 25 \
        --Mapper.ba_global_function_tolerance 1e-6 \
        --Mapper.ba_global_max_num_iterations 50 \
        --Mapper.min_focal_length_ratio 0.1 \
        --Mapper.max_focal_length_ratio 10.0 \
        --Mapper.max_extra_param 1.0 \
        --Mapper.num_threads $MAX_THREADS \
        --Mapper.ba_use_gpu $USE_GPU_BA \
        --Mapper.ba_gpu_index $CUDA_DEVICE

    if [ $? -eq 0 ] && [ -d "$output_path/0" ]; then
        end_timer
        log_success "Sparse reconstruction completed"

        best_recon="0"
        best_count=0
        for recon_dir in "$output_path"/*/; do
            recon_id=$(basename "$recon_dir")
            if [[ "$recon_id" =~ ^[0-9]+$ ]] && [ -f "$recon_dir/images.bin" ]; then
                img_size=$(stat -c%s "$recon_dir/images.bin" 2>/dev/null || echo 0)
                if [ "$img_size" -gt "$best_count" ]; then
                    best_count=$img_size
                    best_recon=$recon_id
                fi
            fi
        done
        log "Best reconstruction: $best_recon (images.bin size: ${best_count} bytes)"
        echo "$best_recon" > "$output_path/best_recon.txt"

        colmap model_converter \
            --input_path "$output_path/$best_recon" \
            --output_path "$output_path/sparse_points.ply" \
            --output_type PLY

        if [ -f "$output_path/sparse_points.ply" ]; then
            log_success "Sparse point cloud exported"
            validate_color_data "$output_path/sparse_points.ply" "sparse"
        fi
    else
        log_error "Sparse reconstruction failed"
        exit 1
    fi
}

convert_to_openmvs_scene() {
    log "Converting COLMAP to OpenMVS scene format"

    start_timer

    sparse_path="$WORKSPACE/tmp/sparse"

    best_recon="0"
    if [ -f "$sparse_path/best_recon.txt" ]; then
        best_recon=$(cat "$sparse_path/best_recon.txt")
        log "Using reconstruction: $best_recon"
    fi

    mkdir -p "$sparse_path/text"

    colmap model_converter \
        --input_path "$sparse_path/$best_recon" \
        --output_path "$sparse_path/text" \
        --output_type TXT

    if [ $? -ne 0 ] || [ ! -f "$sparse_path/text/cameras.txt" ]; then
        log_error "Failed to convert COLMAP model to text format"
        return 1
    fi

    mkdir -p "$sparse_path/$best_recon/sparse"
    cp "$sparse_path/text"/* "$sparse_path/$best_recon/sparse/"

    cd "$WORKSPACE/tmp"

    InterfaceCOLMAP \
        -i "sparse/$best_recon" \
        -o "openmvs/scene.mvs" \
        --image-folder "../converted/" \
        -v 3

    if [ $? -eq 0 ] && [ -f "openmvs/scene.mvs" ]; then
        file_size=$(stat -f%z "openmvs/scene.mvs" 2>/dev/null || stat -c%s "openmvs/scene.mvs" 2>/dev/null)
        if [ "$file_size" -gt 1000 ]; then
            end_timer
            log_success "OpenMVS scene created: scene.mvs (${file_size} bytes)"
            return 0
        fi
    fi

    log_error "OpenMVS scene conversion failed"
    return 1
}

openmvs_dense_reconstruction() {
    log "Dense reconstruction with OpenMVS DensifyPointCloud"
    log "Parameters: resolution-level=$OPENMVS_RESOLUTION_LEVEL, max-resolution=$OPENMVS_MAX_RESOLUTION, views=$OPENMVS_NUMBER_VIEWS, cuda-device=$CUDA_DEVICE"
    log "Internal: iters=$DENSIFY_ITERS, geometric-iters=$DENSIFY_GEOMETRIC_ITERS, sub-resolution-levels=$DENSIFY_SUB_RESOLUTION_LEVELS, max-threads=$DENSIFY_MAX_THREADS"

    start_timer

    cd "$WORKSPACE/tmp"

    scene_file="openmvs/scene.mvs"
    dense_file="openmvs/scene_dense.mvs"

    DensifyPointCloud \
        -i "$scene_file" \
        -o "$dense_file" \
        --cuda-device $CUDA_DEVICE \
        --resolution-level $OPENMVS_RESOLUTION_LEVEL \
        --max-resolution $OPENMVS_MAX_RESOLUTION \
        --min-resolution 480 \
        --number-views $OPENMVS_NUMBER_VIEWS \
        --number-views-fuse 3 \
        --iters $DENSIFY_ITERS \
        --geometric-iters $DENSIFY_GEOMETRIC_ITERS \
        --sub-resolution-levels $DENSIFY_SUB_RESOLUTION_LEVELS \
        --estimate-colors 2 \
        --estimate-normals 2 \
        --postprocess-dmaps 1 \
        --fusion-mode 0 \
        --max-threads $DENSIFY_MAX_THREADS \
        -v 3

    if [ $? -eq 0 ] && [ -f "$dense_file" ]; then
        file_size=$(stat -f%z "$dense_file" 2>/dev/null || stat -c%s "$dense_file" 2>/dev/null)
        if [ "$file_size" -gt 1000 ]; then
            end_timer
            log_success "OpenMVS dense reconstruction completed"
            if [ -f "openmvs/scene_dense.ply" ]; then
                validate_color_data "openmvs/scene_dense.ply" "dense"
            fi
            return 0
        fi
    fi

    log_error "OpenMVS dense reconstruction failed"
    return 1
}

openmvs_mesh_reconstruction() {
    log "OpenMVS mesh reconstruction pipeline"
    log "Parameters: scales=$REFINE_SCALES, decimate=$REFINE_DECIMATE, texmesh-resolution-level=$TEXMESH_RESOLUTION_LEVEL, cuda-device=$CUDA_DEVICE"

    cd "$WORKSPACE/tmp"

    dense_file="openmvs/scene_dense.mvs"
    mesh_file="openmvs/scene_mesh.mvs"
    refined_file="openmvs/scene_mesh_refined.mvs"
    textured_file="openmvs/scene_mesh_textured.mvs"

    if [ ! -f "$dense_file" ]; then
        log_error "Dense file not found for mesh reconstruction"
        return 1
    fi

    log "Step 1: ReconstructMesh"
    start_timer

    ReconstructMesh \
        -i "$dense_file" \
        -o "$mesh_file" \
        --cuda-device $CUDA_DEVICE \
        --export-type ply \
        --max-threads $MAX_THREADS

    if [ $? -ne 0 ] || [ ! -f "$mesh_file" ]; then
        log_error "ReconstructMesh failed"
        return 1
    fi
    end_timer
    log_success "ReconstructMesh completed"

    log "Step 2: RefineMesh"
    start_timer

    RefineMesh \
        -i "$mesh_file" \
        -o "$refined_file" \
        --cuda-device $CUDA_DEVICE \
        --export-type ply \
        --max-threads $MAX_THREADS \
        --resolution-level 1 \
        --min-resolution 512 \
        --max-views 4 \
        --decimate $REFINE_DECIMATE \
        --reduce-memory 1 \
        --scales $REFINE_SCALES \
        --close-holes 20 \
        --regularity-weight 0.2 \
        -v 2

    if [ $? -ne 0 ] || [ ! -f "$refined_file" ]; then
        log_error "RefineMesh failed"
        return 1
    fi
    end_timer
    log_success "RefineMesh completed"

    log "Step 3: TextureMesh"
    start_timer

    TextureMesh \
        -i "$refined_file" \
        -o "$textured_file" \
        --cuda-device $CUDA_DEVICE \
        --export-type obj \
        --max-threads $MAX_THREADS \
        --resolution-level $TEXMESH_RESOLUTION_LEVEL \
        --min-resolution 512 \
        --decimate 1 \
        --close-holes 20 \
        --outlier-threshold 0.06 \
        --cost-smoothness-ratio 0.1 \
        --global-seam-leveling 1 \
        --local-seam-leveling 1 \
        --texture-size-multiple 0 \
        --patch-packing-heuristic 3 \
        -v 2

    if [ $? -eq 0 ] && [ -f "$textured_file" ]; then
        end_timer
        log_success "TextureMesh completed"
        return 0
    else
        log_error "TextureMesh failed"
        return 1
    fi
}

validate_color_data() {
    local ply_file="$1"
    local stage="$2"

    if [ ! -f "$ply_file" ]; then
        log_warning "PLY file not found for validation: $ply_file"
        return 1
    fi

    local color_check=$(strings "$ply_file" | grep -i "property.*red\|property.*green\|property.*blue" | wc -l)
    local file_size=$(stat -f%z "$ply_file" 2>/dev/null || stat -c%s "$ply_file" 2>/dev/null)
    local size_mb=$((file_size / 1024 / 1024))

    if [ "$color_check" -ge 3 ]; then
        log_success "$stage point cloud validation: colors present (${size_mb}MB)"
        return 0
    else
        log_warning "$stage point cloud validation: no colors detected (${size_mb}MB)"
        return 1
    fi
}

organize_results() {
    log "Organizing results to result directory"

    local result_dir="$WORKSPACE/result"
    local timestamp=$(date '+%Y%m%d_%H%M%S')
    local tmp_dir="$WORKSPACE/tmp"

    if [ -f "$tmp_dir/sparse/sparse_points.ply" ]; then
        cp "$tmp_dir/sparse/sparse_points.ply" "$result_dir/sparse_points.ply"
        log_success "Copied sparse point cloud"
    fi

    if [ -f "$tmp_dir/openmvs/scene_dense.ply" ]; then
        cp "$tmp_dir/openmvs/scene_dense.ply" "$result_dir/dense_points.ply"
        log_success "Copied dense point cloud"
    fi

    if [ -f "$tmp_dir/openmvs/scene_mesh_textured.obj" ]; then
        cp "$tmp_dir/openmvs/scene_mesh_textured.obj" "$result_dir/mesh.obj"
        log_success "Copied textured mesh (OBJ)"
    fi

    if [ -f "$tmp_dir/openmvs/scene_mesh_textured.mtl" ]; then
        cp "$tmp_dir/openmvs/scene_mesh_textured.mtl" "$result_dir/mesh.mtl"
        log_success "Copied material file (MTL)"
    fi

    for texture_file in "$tmp_dir/openmvs"/*.png "$tmp_dir/openmvs"/*.jpg; do
        if [ -f "$texture_file" ]; then
            texture_name=$(basename "$texture_file")
            cp "$texture_file" "$result_dir/$texture_name"
            log_success "Copied texture: $texture_name"
        fi
    done

    if [ -f "$tmp_dir/sparse/text/cameras.txt" ]; then
        cp "$tmp_dir/sparse/text/cameras.txt" "$result_dir/cameras.txt"
        log_success "Copied camera parameters"
    fi

    if [ -f "$tmp_dir/sparse/text/images.txt" ]; then
        cp "$tmp_dir/sparse/text/images.txt" "$result_dir/images.txt"
        log_success "Copied image parameters"
    fi

    generate_metadata "$result_dir" "$timestamp"

    log_success "Results organized in: $result_dir"
}

generate_metadata() {
    local result_dir="$1"
    local timestamp="$2"
    local metadata_file="$result_dir/reconstruction.json"

    local image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \
        \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" \) | wc -l)

    local registered_images=0
    if [ -f "$WORKSPACE/tmp/sparse/text/images.txt" ]; then
        registered_images=$(grep -cE "\.(jpg|jpeg|png|tiff?|JPG|JPEG|PNG|TIFF?)$" \
            "$WORKSPACE/tmp/sparse/text/images.txt" 2>/dev/null || echo "0")
    fi

    local sparse_points=0
    if [ -f "$WORKSPACE/tmp/sparse/text/points3D.txt" ]; then
        sparse_points=$(grep -c "^[0-9]" "$WORKSPACE/tmp/sparse/text/points3D.txt" 2>/dev/null || echo "0")
    fi

    cat > "$metadata_file" << EOF
{
  "reconstruction_info": {
    "timestamp": "$timestamp",
    "workspace": "$WORKSPACE",
    "output_type": "$OUTPUT_TYPE",
    "gpu_available": "${GPU_AVAILABLE:-false}",
    "matcher_type": "$MATCHER_TYPE",
    "parameters": {
      "max_image_size": $MAX_IMAGE_SIZE,
      "max_features": $MAX_NUM_FEATURES,
      "max_num_matches": $MAX_NUM_MATCHES,
      "guided_matching": $GUIDED_MATCHING,
      "max_threads": $MAX_THREADS,
      "openmvs_resolution_level": $OPENMVS_RESOLUTION_LEVEL,
      "openmvs_max_resolution": $OPENMVS_MAX_RESOLUTION,
      "openmvs_number_views": $OPENMVS_NUMBER_VIEWS,
      "densify_iters": $DENSIFY_ITERS,
      "densify_geometric_iters": $DENSIFY_GEOMETRIC_ITERS,
      "densify_sub_resolution_levels": $DENSIFY_SUB_RESOLUTION_LEVELS,
      "densify_max_threads": $DENSIFY_MAX_THREADS,
      "refine_scales": $REFINE_SCALES,
      "refine_decimate": $REFINE_DECIMATE,
      "texmesh_resolution_level": $TEXMESH_RESOLUTION_LEVEL
    }
  },
  "statistics": {
    "input_images": $image_count,
    "registered_images": $registered_images,
    "sparse_points": $sparse_points
  },
  "output_files": {
    "sparse_points": "sparse_points.ply",
    "dense_points": "dense_points.ply",
    "textured_mesh": "mesh.obj",
    "material_file": "mesh.mtl",
    "cameras": "cameras.txt",
    "images": "images.txt"
  }
}
EOF

    log_success "Generated metadata: reconstruction.json"
}

run_reconstruction_pipeline() {
    log "Running reconstruction pipeline (output type: $OUTPUT_TYPE)"

    check_workspace
    extract_features
    match_features
    sparse_reconstruction

    if convert_to_openmvs_scene; then
        if openmvs_dense_reconstruction; then
            if [ "$OUTPUT_TYPE" = "dense_mesh" ]; then
                openmvs_mesh_reconstruction
            fi
            organize_results
            log_success "Reconstruction pipeline completed successfully"
            return 0
        fi
    fi

    log_error "Reconstruction pipeline failed"
    return 1
}

generate_report() {
    log "Generating reconstruction report"

    echo
    echo "============================================"
    echo "COLMAP + OpenMVS Reconstruction Report"
    echo "============================================"
    echo "Workspace: $WORKSPACE"
    echo "Output type: $OUTPUT_TYPE"
    echo "GPU available: ${GPU_AVAILABLE:-false}"
    echo "Use GPU (COLMAP): $USE_GPU"
    echo "CUDA device (OpenMVS): $CUDA_DEVICE"
    echo "BA GPU: $USE_GPU_BA"
    echo "Matcher: $MATCHER_TYPE"
    echo ""
    echo "COLMAP: max-image-size=$MAX_IMAGE_SIZE, max-features=$MAX_NUM_FEATURES, max-matches=$MAX_NUM_MATCHES, guided=$GUIDED_MATCHING, threads=$MAX_THREADS"
    echo "Densify: resolution-level=$OPENMVS_RESOLUTION_LEVEL, max-resolution=$OPENMVS_MAX_RESOLUTION, views=$OPENMVS_NUMBER_VIEWS"
    echo "Densify internal: iters=$DENSIFY_ITERS, geometric-iters=$DENSIFY_GEOMETRIC_ITERS, sub-resolution-levels=$DENSIFY_SUB_RESOLUTION_LEVELS, max-threads=$DENSIFY_MAX_THREADS"
    echo "RefineMesh: scales=$REFINE_SCALES, decimate=$REFINE_DECIMATE"
    echo "TextureMesh: resolution-level=$TEXMESH_RESOLUTION_LEVEL"
    echo

    local image_count=$(find "$WORKSPACE/converted" -maxdepth 1 -type f \
        \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tiff" -o -iname "*.tif" \) | wc -l)
    echo "Input images: $image_count"

    local best_recon="0"
    if [ -f "$WORKSPACE/tmp/sparse/best_recon.txt" ]; then
        best_recon=$(cat "$WORKSPACE/tmp/sparse/best_recon.txt")
    fi

    if [ -f "$WORKSPACE/tmp/sparse/$best_recon/points3D.bin" ]; then
        echo "Sparse reconstruction: SUCCESS"
        if [ -f "$WORKSPACE/tmp/sparse/text/points3D.txt" ]; then
            point_count=$(grep -c "^[0-9]" "$WORKSPACE/tmp/sparse/text/points3D.txt" 2>/dev/null || echo "0")
            echo "Sparse 3D points: $point_count"
        fi
        if [ -f "$WORKSPACE/tmp/sparse/text/images.txt" ]; then
            registered_images=$(grep -cE "\.(jpg|jpeg|png|tiff?|JPG|JPEG|PNG|TIFF?)$" \
                "$WORKSPACE/tmp/sparse/text/images.txt" 2>/dev/null || echo "0")
            echo "Registered images: $registered_images/$image_count"
        fi
    else
        echo "Sparse reconstruction: FAILED"
    fi

    if [ -f "$WORKSPACE/tmp/openmvs/scene.mvs" ]; then
        echo "OpenMVS scene conversion: SUCCESS"
    else
        echo "OpenMVS scene conversion: FAILED"
    fi

    if [ -f "$WORKSPACE/tmp/openmvs/scene_dense.mvs" ]; then
        echo "OpenMVS dense reconstruction: SUCCESS"
    else
        echo "OpenMVS dense reconstruction: FAILED"
    fi

    if [ -f "$WORKSPACE/tmp/openmvs/scene_mesh.mvs" ]; then
        echo "OpenMVS ReconstructMesh: SUCCESS"
    else
        echo "OpenMVS ReconstructMesh: NOT EXECUTED"
    fi

    if [ -f "$WORKSPACE/tmp/openmvs/scene_mesh_refined.mvs" ]; then
        echo "OpenMVS RefineMesh: SUCCESS"
    else
        echo "OpenMVS RefineMesh: NOT EXECUTED"
    fi

    if [ -f "$WORKSPACE/tmp/openmvs/scene_mesh_textured.obj" ]; then
        echo "OpenMVS TextureMesh: SUCCESS"
    else
        echo "OpenMVS TextureMesh: NOT EXECUTED"
    fi

    echo
    echo "Final outputs in result directory:"
    for output_file in "$WORKSPACE/result"/*.obj "$WORKSPACE/result"/*.mtl \
                       "$WORKSPACE/result"/*.ply "$WORKSPACE/result"/*.txt \
                       "$WORKSPACE/result"/*.json "$WORKSPACE/result"/*.png \
                       "$WORKSPACE/result"/*.jpg; do
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
    echo "Pipeline: COLMAP sparse -> OpenMVS dense -> ReconstructMesh -> RefineMesh -> TextureMesh"
    echo "Result location: $WORKSPACE/result"
    echo "============================================"
}

main() {
    overall_start=$(date +%s)

    log "Starting COLMAP + OpenMVS reconstruction pipeline"

    parse_arguments "$@"
    detect_environment
    validate_parameters

    log "workspace=$WORKSPACE, output-type=$OUTPUT_TYPE"
    log "GPU mode: GPU_AVAILABLE=${GPU_AVAILABLE:-false}, USE_GPU=$USE_GPU, CUDA_DEVICE=$CUDA_DEVICE, USE_GPU_BA=$USE_GPU_BA"
    log "Threads: $MAX_THREADS, Matcher threshold: $MATCHER_THRESHOLD"

    run_reconstruction_pipeline
    result=$?

    overall_end=$(date +%s)
    overall_elapsed=$((overall_end - overall_start))
    overall_minutes=$((overall_elapsed / 60))
    overall_seconds=$((overall_elapsed % 60))

    generate_report

    echo
    if [ $result -eq 0 ]; then
        log_success "Reconstruction pipeline completed successfully"
    else
        log_error "Reconstruction pipeline failed"
    fi
    log "Total time: ${overall_minutes}m ${overall_seconds}s"

    exit $result
}

main "$@"