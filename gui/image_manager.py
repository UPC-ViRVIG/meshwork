# gui/image_manager.py
import os
import glob
import shutil
import time
from typing import List, Tuple, Dict, Any
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QListWidget, QListWidgetItem, QApplication
)
from PySide6.QtCore import Qt, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap, QMouseEvent
from logger import get_logger
from core.utils import ensure_directory_exists

RAW_EXTENSIONS = ['.cr2', '.nef', '.arw', '.dng', '.raw']

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False

RAWPY_CONFIG_THUMBNAIL = {
    'use_camera_wb': True,
    'half_size': False,
    'no_auto_bright': True,
    'output_bps': 8,
    'output_format': 'JPEG',
    'file_extension': '.jpg'
}

RAWPY_CONFIG_CONVERTED = {
    'use_camera_wb': True,
    'half_size': False,
    'no_auto_bright': True,
    'output_bps': 8,
    'bright': 1.0,
    'demosaic_algorithm': rawpy.DemosaicAlgorithm.AHD,
    'output_color': rawpy.ColorSpace.sRGB,
    'gamma': (2.2, 4.5),
    'output_format': 'PNG',
    'file_extension': '.png'
}

STYLE_SELECTED_BORDER = "border: 3px solid #4ade80;"
STYLE_DEFAULT_BORDER = "border: 1px solid #555;"
STYLE_ERROR_BORDER = "border: 1px solid #ff5555;"
STYLE_RAW_BORDER = "border: 2px solid #ffa500;"

STYLE_BASE_BG = "background-color: #3a3a3a;"
STYLE_ERROR_BG = "background-color: #2a2a2a;"
STYLE_BASE_SIZE = "font-size: 8px;"

STYLE_DEFAULT_COLOR = "color: #888;"
STYLE_ERROR_COLOR = "color: #ff5555;"
STYLE_RAW_COLOR = "color: #ffa500;"
STYLE_LOADED_COLOR = "color: #fff;"

def get_thumbnails_directory(image_folder: str) -> str:
    folder_name = os.path.basename(image_folder.rstrip('/\\'))
    import tempfile
    system_temp = tempfile.gettempdir()
    cache_dir = os.path.join(system_temp, "meshwork_thumbnails")
    ensure_directory_exists(cache_dir)
    return os.path.join(cache_dir, f"{folder_name}_thumbnails")

def get_converted_directory(output_folder: str) -> str:
    return os.path.join(output_folder, "converted")

def create_processing_file(directory: str) -> bool:
    if not os.path.exists(directory):
        return False

    processing_file = os.path.join(directory, ".processing")
    try:
        with open(processing_file, 'w') as f:
            f.write(str(time.time()))
        return True
    except (OSError, IOError):
        return False

def remove_processing_file(directory: str) -> bool:
    processing_file = os.path.join(directory, ".processing")
    if os.path.exists(processing_file):
        try:
            os.remove(processing_file)
            return True
        except (OSError, IOError):
            return False
    return True

def has_processing_file(directory: str) -> bool:
    processing_file = os.path.join(directory, ".processing")
    return os.path.exists(processing_file)

def scan_supported_images(folder: str, supported_formats: List[str]) -> List[str]:
    if not os.path.exists(folder):
        return []

    image_files = []
    for ext in supported_formats:
        pattern = os.path.join(folder, f"*{ext}")
        image_files.extend(glob.glob(pattern))
        pattern = os.path.join(folder, f"*{ext.upper()}")
        image_files.extend(glob.glob(pattern))

    return sorted(list(set(image_files)))

def count_files_in_directory(directory: str) -> int:
    if not os.path.exists(directory):
        return 0

    try:
        return len([f for f in os.listdir(directory)
                   if os.path.isfile(os.path.join(directory, f)) and not f.startswith('.')])
    except (OSError, IOError):
        return 0

class ClickableLabel(QLabel):
    clicked = Signal(bool, bool)  # emits ctrl_modifier, shift_modifier

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            modifiers = QApplication.keyboardModifiers()
            ctrl_modifier = bool(modifiers & Qt.ControlModifier)
            shift_modifier = bool(modifiers & Qt.ShiftModifier)
            self.clicked.emit(ctrl_modifier, shift_modifier)
        super().mousePressEvent(event)

class ImageProcessor:
    def __init__(self):
        self.logger = get_logger()
        self.default_quality = 90
        self.logger.info(f"ImageProcessor initialized, rawpy_available: {RAWPY_AVAILABLE}")

    def is_raw_format(self, file_path: str) -> bool:
        return any(file_path.lower().endswith(ext) for ext in RAW_EXTENSIONS)

    def get_supported_formats(self) -> List[str]:
        standard_formats = ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp']
        raw_formats = RAW_EXTENSIONS if RAWPY_AVAILABLE else []
        return standard_formats + raw_formats

    def convert_image(self, src_path: str, dst_path: str, target_size: Tuple[int, int], quality: int, rawpy_config: dict = None) -> bool:
        self.logger.debug(f"Converting: {os.path.basename(src_path)} -> {os.path.basename(dst_path)}, size: {target_size}")

        if not os.path.exists(src_path):
            self.logger.error(f"Source file does not exist: {src_path}")
            return False

        if not os.access(src_path, os.R_OK):
            self.logger.error(f"Cannot read source file: {src_path}")
            return False

        dst_dir = os.path.dirname(dst_path)
        if dst_dir and not os.path.exists(dst_dir):
            self.logger.debug(f"Creating destination directory: {dst_dir}")
            try:
                os.makedirs(dst_dir, exist_ok=True)
            except OSError as e:
                self.logger.error(f"Failed to create destination directory {dst_dir}: {e}")
                return False

        if self.is_raw_format(src_path):
            self.logger.debug(f"Processing as RAW image: {os.path.basename(src_path)}")
            return self._convert_raw_image(src_path, dst_path, target_size, quality, rawpy_config)
        else:
            self.logger.debug(f"Processing as standard image: {os.path.basename(src_path)}")
            return self._convert_standard_image(src_path, dst_path, target_size, quality)

    def _convert_raw_image(self, src_path: str, dst_path: str, target_size: Tuple[int, int], quality: int, rawpy_config: dict = None) -> bool:
        if not RAWPY_AVAILABLE:
            self.logger.error("rawpy library not available for RAW processing")
            return False

        if rawpy_config is None:
            rawpy_config = RAWPY_CONFIG_THUMBNAIL

        config_copy = rawpy_config.copy()
        output_format = config_copy.pop('output_format', 'JPEG')
        file_extension = config_copy.pop('file_extension', '.jpg')

        try:
            self.logger.debug(f"Opening RAW file with rawpy: {os.path.basename(src_path)}")
            with rawpy.imread(src_path) as raw:
                self.logger.debug(f"Processing RAW data, config: {config_copy}")
                rgb = raw.postprocess(**config_copy)

            self.logger.debug(f"RAW processed to RGB array, shape: {rgb.shape}")

            try:
                from PIL import Image
                self.logger.debug("Using PIL for RAW conversion")
                pil_image = Image.fromarray(rgb)

                if target_size != (0, 0):
                    self.logger.debug(f"Resizing RAW image from {pil_image.size} to {target_size}")
                    pil_image = pil_image.resize(target_size, Image.Resampling.LANCZOS)

                if output_format == 'PNG':
                    self.logger.debug("Saving RAW image with PIL as PNG")
                    pil_image.save(dst_path, "PNG")
                else:
                    self.logger.debug(f"Saving RAW image with PIL as JPEG, quality: {quality}")
                    pil_image.save(dst_path, "JPEG", quality=quality, optimize=True)

                self.logger.debug(f"RAW conversion completed successfully: {os.path.basename(dst_path)}")
                return True

            except ImportError:
                self.logger.debug("PIL not available, using Qt for RAW conversion")
                from PySide6.QtGui import QImage
                height, width = rgb.shape[:2]
                bytes_per_line = 3 * width
                q_image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)

                if q_image.isNull():
                    self.logger.error("Failed to create QImage from RAW data")
                    return False

                if target_size != (0, 0):
                    self.logger.debug(f"Resizing RAW image with Qt to {target_size}")
                    q_image = q_image.scaled(target_size[0], target_size[1])

                if output_format == 'PNG':
                    self.logger.debug("Saving RAW image with Qt as PNG")
                    success = q_image.save(dst_path, "PNG")
                else:
                    self.logger.debug(f"Saving RAW image with Qt as JPEG, quality: {quality}")
                    success = q_image.save(dst_path, "JPEG", quality)

                if success:
                    self.logger.debug(f"RAW conversion completed successfully: {os.path.basename(dst_path)}")
                else:
                    self.logger.error(f"Failed to save RAW image with Qt: {dst_path}")
                return success

        except Exception as e:
            self.logger.error(f"RAW conversion failed for {os.path.basename(src_path)}: {type(e).__name__}: {str(e)}")
            return False

    def _convert_standard_image(self, src_path: str, dst_path: str, target_size: Tuple[int, int], quality: int) -> bool:
        if src_path.lower().endswith(('.jpg', '.jpeg')) and target_size == (0, 0):
            self.logger.debug(f"Direct copy for JPEG file: {os.path.basename(src_path)}")
            try:
                import shutil
                shutil.copy2(src_path, dst_path)
                self.logger.debug(f"JPEG copy completed: {os.path.basename(dst_path)}")
                return True
            except (OSError, IOError) as e:
                self.logger.error(f"Failed to copy JPEG file {os.path.basename(src_path)}: {e}")
                return False

        try:
            self.logger.debug(f"Loading standard image with QPixmap: {os.path.basename(src_path)}")
            pixmap = QPixmap(src_path)
            if pixmap.isNull():
                self.logger.error(f"Failed to load image with QPixmap: {os.path.basename(src_path)}")
                return False

            original_size = (pixmap.width(), pixmap.height())
            self.logger.debug(f"Image loaded, original size: {original_size}")

            if target_size != (0, 0):
                self.logger.debug(f"Scaling image from {original_size} to {target_size}")
                pixmap = pixmap.scaled(target_size[0], target_size[1],
                                    Qt.KeepAspectRatio, Qt.SmoothTransformation)

            self.logger.debug(f"Saving standard image, quality: {quality}")
            success = pixmap.save(dst_path, "JPEG", quality)
            if success:
                self.logger.debug(f"Standard conversion completed: {os.path.basename(dst_path)}")
            else:
                self.logger.error(f"Failed to save standard image: {dst_path}")
            return success

        except Exception as e:
            self.logger.error(f"Standard conversion failed for {os.path.basename(src_path)}: {type(e).__name__}: {str(e)}")
            return False

class ConversionTask(QRunnable):
    def __init__(self, src_path: str, dst_path: str, target_size: Tuple[int, int],
                 quality: int, pingpong: str, signal_router, image_processor: ImageProcessor, rawpy_config: dict = None):
        super().__init__()
        self.src_path = src_path
        self.dst_path = dst_path
        self.target_size = target_size
        self.quality = quality
        self.pingpong = pingpong
        self.signal_router = signal_router
        self.image_processor = image_processor
        self.rawpy_config = rawpy_config
        self.logger = get_logger()

    def run(self):
        self.logger.debug(f"Starting conversion task: {os.path.basename(self.src_path)} ({self.pingpong})")

        success = self.image_processor.convert_image(
            self.src_path, self.dst_path, self.target_size, self.quality, self.rawpy_config
        )

        if success:
            self.logger.debug(f"Conversion task completed: {os.path.basename(self.src_path)} ({self.pingpong})")
            error = ""
        else:
            error = f"Conversion failed for {os.path.basename(self.src_path)}"
            self.logger.error(f"Conversion task failed: {os.path.basename(self.src_path)} ({self.pingpong})")

        self._emit_result(success, error)

    def _emit_result(self, success: bool, error: str = ""):
        if self.signal_router:
            self.signal_router.emit('recon.image_converted', {
                'src_path': self.src_path,
                'dst_path': self.dst_path,
                'success': success,
                'error': error,
                'pingpong': self.pingpong
            })
        else:
            self.logger.error("No signal_router available for emitting result")

class ImagePreviewPanel(QWidget):
    selection_changed = Signal(int)

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.image_processor = ImageProcessor()
        self.thread_pool = QThreadPool()

        self.thumbnail_task_running = False
        self.converted_task_running = False
        self.thumbnail_completed = False
        self.converted_completed = False

        self.image_items = []
        self.current_image_folder = ""
        self.current_output_folder = ""
        self.last_single_selection_index = None

        self.thumbnail_tasks_total = 0
        self.thumbnail_tasks_completed = 0
        self.converted_tasks_total = 0
        self.converted_tasks_completed = 0

        self._setup_ui()
        self._setup_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()

        title = QLabel("Image Selection")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all_images)
        header_layout.addWidget(self.select_all_btn)

        self.invert_select_btn = QPushButton("Invert Select")
        self.invert_select_btn.clicked.connect(self._invert_selection)
        header_layout.addWidget(self.invert_select_btn)

        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(self._select_no_images)
        header_layout.addWidget(self.select_none_btn)

        layout.addLayout(header_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(6)

        self.scroll_area.setWidget(self.grid_widget)
        layout.addWidget(self.scroll_area)

        self.status_label = QLabel("No images loaded")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.status_label)

    def _setup_signals(self):
        if self.signal_router:
            self.signal_router.subscribe('recon.folder_changed', self._on_folder_changed, 'ImagePreviewPanel')
            self.signal_router.subscribe('recon.image_converted', self._on_image_converted, 'ImagePreviewPanel')

    def _calculate_columns(self):
        available_width = self.scroll_area.viewport().width()
        item_width = 140
        margin = 20
        cols = max(1, (available_width - margin) // item_width)
        return cols

    def _get_item_index(self, target_item: Dict[str, Any]) -> int:
        for i, item in enumerate(self.image_items):
            if item == target_item:
                return i
        return -1

    def _get_range_items(self, start_index: int, end_index: int) -> List[Dict[str, Any]]:
        if start_index < 0 or end_index < 0:
            return []

        min_index = min(start_index, end_index)
        max_index = max(start_index, end_index)

        if min_index >= len(self.image_items) or max_index >= len(self.image_items):
            return []

        return self.image_items[min_index:max_index + 1]

    def _set_item_selection(self, item: Dict[str, Any], selected: bool):
        item['selected'] = selected
        self._update_item_style(item)

    def _get_item_selection(self, item: Dict[str, Any]) -> bool:
        return item.get('selected', False)

    def _get_thumbnail_style(self, item: Dict[str, Any], is_loaded: bool = False, is_error: bool = False) -> str:
        base_style = STYLE_BASE_BG + STYLE_BASE_SIZE

        if is_error:
            return base_style + STYLE_ERROR_BG + STYLE_ERROR_BORDER + STYLE_ERROR_COLOR
        elif item['is_raw'] and not is_loaded:
            return base_style + STYLE_RAW_BORDER + STYLE_RAW_COLOR
        elif not is_loaded:
            return base_style + STYLE_DEFAULT_BORDER + STYLE_DEFAULT_COLOR
        else:
            if self._get_item_selection(item):
                return base_style + STYLE_SELECTED_BORDER + STYLE_LOADED_COLOR
            else:
                return base_style + STYLE_DEFAULT_BORDER + STYLE_LOADED_COLOR

    def _update_item_style(self, item: Dict[str, Any], is_loaded: bool = True, is_error: bool = False):
        if 'thumbnail_label' in item:
            style = self._get_thumbnail_style(item, is_loaded, is_error)
            item['thumbnail_label'].setStyleSheet(style)

    def _on_thumbnail_clicked(self, ctrl_modifier: bool, shift_modifier: bool, item: Dict[str, Any]):
        current_index = self._get_item_index(item)

        if shift_modifier and self.last_single_selection_index is not None:
            range_items = self._get_range_items(self.last_single_selection_index, current_index)
            for range_item in range_items:
                self._set_item_selection(range_item, True)
            self.last_single_selection_index = current_index

        elif ctrl_modifier:
            current_selection = self._get_item_selection(item)
            self._set_item_selection(item, not current_selection)

        else:
            for other_item in self.image_items:
                if other_item != item:
                    self._set_item_selection(other_item, False)
            self._set_item_selection(item, True)
            self.last_single_selection_index = current_index

        self._update_status_label()
        self._emit_selection_changed()

    def _invert_selection(self):
        for item in self.image_items:
            current_state = self._get_item_selection(item)
            self._set_item_selection(item, not current_state)
        self._update_status_label()
        self._emit_selection_changed()

    def _on_folder_changed(self, data: Dict[str, Any]):
        folder_type = data.get('folder_type', '')
        path = data.get('path', '')

        if folder_type == 'input':
            self.current_image_folder = path
            self._process_image_folder_change(path)
        elif folder_type == 'output':
            self.current_output_folder = path
            self._process_output_folder_change(path)

    def _process_image_folder_change(self, folder_path: str):
        if not folder_path or not os.path.exists(folder_path):
            return

        self.clear_preview()

        image_files = self._scan_source_directory(folder_path)
        if not image_files:
            self.status_label.setText("No supported images found")
            return

        self._create_image_items(image_files)
        self._try_load_existing_thumbnails()

        thumbnails_consistent = self._check_thumbnails_consistency(folder_path)
        if not thumbnails_consistent:
            self._start_thumbnails_task(image_files)

    def _process_output_folder_change(self, folder_path: str):
        if not folder_path or not os.path.exists(folder_path):
            return

        if not self.current_image_folder:
            return

        image_files = self._scan_source_directory(self.current_image_folder)
        if not image_files:
            return

        converted_consistent = self._check_converted_consistency(folder_path)
        if not converted_consistent:
            self._start_converted_task(image_files)

    def _scan_source_directory(self, folder_path: str) -> List[str]:
        supported_formats = self.image_processor.get_supported_formats()
        return scan_supported_images(folder_path, supported_formats)

    def _check_thumbnails_consistency(self, folder_path: str) -> bool:
        thumbnails_dir = get_thumbnails_directory(folder_path)
        self.logger.debug(f"Checking thumbnails consistency: {thumbnails_dir}")

        if has_processing_file(thumbnails_dir):
            self.logger.info("Found .processing file in thumbnails directory, rebuilding")
            self._delete_and_recreate_directory(thumbnails_dir)
            return False

        image_files = self._scan_source_directory(folder_path)
        thumbnail_count = count_files_in_directory(thumbnails_dir)

        self.logger.debug(f"Thumbnails consistency check: {len(image_files)} source files, {thumbnail_count} thumbnails")

        if len(image_files) != thumbnail_count:
            self.logger.info(f"Thumbnails count mismatch ({len(image_files)} != {thumbnail_count}), rebuilding")
            self._delete_and_recreate_directory(thumbnails_dir)
            return False

        self.thumbnail_completed = True
        self.logger.debug("Thumbnails directory is consistent")
        return True

    def _check_converted_consistency(self, output_folder: str) -> bool:
        converted_dir = get_converted_directory(output_folder)
        self.logger.debug(f"Checking converted consistency: {converted_dir}")

        if has_processing_file(converted_dir):
            self.logger.info("Found .processing file in converted directory, rebuilding")
            self._delete_and_recreate_directory(converted_dir)
            return False

        image_files = self._scan_source_directory(self.current_image_folder)
        converted_count = count_files_in_directory(converted_dir)

        self.logger.debug(f"Converted consistency check: {len(image_files)} source files, {converted_count} converted files")

        if len(image_files) != converted_count:
            self.logger.info(f"Converted count mismatch ({len(image_files)} != {converted_count}), rebuilding")
            self._delete_and_recreate_directory(converted_dir)
            return False

        self.converted_completed = True
        self.logger.debug("Converted directory is consistent")
        return True

    def _delete_and_recreate_directory(self, directory: str):
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)
            except (OSError, IOError):
                pass

        ensure_directory_exists(directory)

    def _start_thumbnails_task(self, image_files: List[str]):
        if self.thumbnail_task_running:
            self.logger.warning("Thumbnail task already running, skipping")
            return

        thumbnails_dir = get_thumbnails_directory(self.current_image_folder)
        ensure_directory_exists(thumbnails_dir)
        create_processing_file(thumbnails_dir)

        self.thumbnail_task_running = True
        self.thumbnail_completed = False
        self.thumbnail_tasks_total = len(image_files)
        self.thumbnail_tasks_completed = 0

        self.logger.info(f"Starting thumbnail generation for {self.thumbnail_tasks_total} files")
        self.logger.debug(f"Thumbnails directory: {thumbnails_dir}")

        for image_file in image_files:
            base_name = os.path.splitext(os.path.basename(image_file))[0]
            file_extension = RAWPY_CONFIG_THUMBNAIL.get('file_extension', '.jpg')
            dst_path = os.path.join(thumbnails_dir, f"{base_name}{file_extension}")

            task = ConversionTask(
                image_file, dst_path, (128, 128), 85, 'thumbnail',
                self.signal_router, self.image_processor, RAWPY_CONFIG_THUMBNAIL.copy()
            )
            task.setAutoDelete(True)
            self.thread_pool.start(task, priority=1)

        self.logger.debug(f"Queued {len(image_files)} thumbnail tasks")

    def _start_converted_task(self, image_files: List[str]):
        if self.converted_task_running or not self.current_output_folder:
            if self.converted_task_running:
                self.logger.warning("Converted task already running, skipping")
            else:
                self.logger.warning("No output folder set, skipping converted task")
            return

        converted_dir = get_converted_directory(self.current_output_folder)
        ensure_directory_exists(converted_dir)
        create_processing_file(converted_dir)

        self.converted_task_running = True
        self.converted_completed = False
        self.converted_tasks_total = len(image_files)
        self.converted_tasks_completed = 0

        self.logger.info(f"Starting image conversion for {self.converted_tasks_total} files")
        self.logger.debug(f"Converted directory: {converted_dir}")

        for image_file in image_files:
            base_name = os.path.splitext(os.path.basename(image_file))[0]

            if self.image_processor.is_raw_format(image_file):
                file_extension = RAWPY_CONFIG_CONVERTED.get('file_extension', '.png')
                dst_path = os.path.join(converted_dir, f"{base_name}{file_extension}")
                rawpy_config = RAWPY_CONFIG_CONVERTED.copy()
            else:
                dst_path = os.path.join(converted_dir, os.path.basename(image_file))
                rawpy_config = None

            task = ConversionTask(
                image_file, dst_path, (0, 0), 90, 'converted',
                self.signal_router, self.image_processor, rawpy_config
            )
            task.setAutoDelete(True)
            self.thread_pool.start(task, priority=0)

        self.logger.debug(f"Queued {len(image_files)} conversion tasks")

    def _on_image_converted(self, data: Dict[str, Any]):
        pingpong = data.get('pingpong', '')
        success = data.get('success', False)
        src_path = data.get('src_path', '')
        dst_path = data.get('dst_path', '')
        error = data.get('error', '')

        if not success and error:
            self.logger.warning(f"Conversion failed ({pingpong}): {error}")

        if pingpong == 'thumbnail':
            self.thumbnail_tasks_completed += 1
            if success:
                self._update_thumbnail_display(src_path, dst_path)
            else:
                self.logger.error(f"Thumbnail generation failed for {os.path.basename(src_path)}: {error}")
            self._check_task_completion('thumbnail')
        elif pingpong == 'converted':
            self.converted_tasks_completed += 1
            if not success:
                self.logger.error(f"Image conversion failed for {os.path.basename(src_path)}: {error}")
            self._check_task_completion('converted')

    def _update_thumbnail_display(self, src_path: str, thumbnail_path: str):
        for item in self.image_items:
            if item['path'] == src_path:
                label = item['thumbnail_label']
                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    label.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    label.setText("")
                    self._update_item_style(item, is_loaded=True, is_error=False)
                else:
                    label.setText("Error")
                    self._update_item_style(item, is_loaded=False, is_error=True)
                break

    def _check_task_completion(self, phase: str):
        if phase == 'thumbnail':
            self.logger.debug(f"Thumbnail progress: {self.thumbnail_tasks_completed}/{self.thumbnail_tasks_total}")
            if self.thumbnail_tasks_completed >= self.thumbnail_tasks_total:
                self.thumbnail_task_running = False
                self.thumbnail_completed = True

                thumbnails_dir = get_thumbnails_directory(self.current_image_folder)
                remove_processing_file(thumbnails_dir)

                self.logger.info(f"Thumbnail generation completed: {self.thumbnail_tasks_completed}/{self.thumbnail_tasks_total}")
                self._emit_phase_completed('thumbnail', self.thumbnail_tasks_completed, self.thumbnail_tasks_total)

        elif phase == 'converted':
            self.logger.debug(f"Converted progress: {self.converted_tasks_completed}/{self.converted_tasks_total}")
            if self.converted_tasks_completed >= self.converted_tasks_total:
                self.converted_task_running = False
                self.converted_completed = True

                converted_dir = get_converted_directory(self.current_output_folder)
                remove_processing_file(converted_dir)

                self.logger.info(f"Image conversion completed: {self.converted_tasks_completed}/{self.converted_tasks_total}")
                self._emit_phase_completed('converted', self.converted_tasks_completed, self.converted_tasks_total)

    def _emit_phase_completed(self, phase: str, success_count: int, total_count: int):
        if self.signal_router:
            self.signal_router.emit('recon.image_all_converted', {
                'phase': phase,
                'success_count': success_count,
                'total_count': total_count
            })

    def _create_image_items(self, image_files: List[str]):
        cols = self._calculate_columns()
        for i, image_file in enumerate(image_files):
            row = i // cols
            col = i % cols

            item_widget = self._create_image_item(image_file)
            self.grid_layout.addWidget(item_widget, row, col)

        self._update_status_label()

    def _try_load_existing_thumbnails(self):
        if not self.current_image_folder:
            return

        thumbnails_dir = get_thumbnails_directory(self.current_image_folder)
        if not os.path.exists(thumbnails_dir):
            self.logger.debug("Thumbnails directory does not exist, skipping load")
            return

        self.logger.debug(f"Trying to load existing thumbnails from: {thumbnails_dir}")
        loaded_count = 0

        for item in self.image_items:
            src_path = item['path']
            base_name = os.path.splitext(os.path.basename(src_path))[0]
            thumbnail_path = os.path.join(thumbnails_dir, f"{base_name}.jpg")

            if os.path.exists(thumbnail_path):
                self._update_thumbnail_display(src_path, thumbnail_path)
                loaded_count += 1

        self.logger.debug(f"Loaded {loaded_count} existing thumbnails")

    def _create_image_item(self, image_path: str) -> QWidget:
        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(4, 4, 4, 4)
        item_layout.setSpacing(4)

        thumbnail_label = ClickableLabel()
        thumbnail_label.setFixedSize(128, 128)
        thumbnail_label.setAlignment(Qt.AlignCenter)

        if self.image_processor.is_raw_format(image_path):
            thumbnail_label.setText("RAW\nLoading...")
        else:
            thumbnail_label.setText("Loading...")

        item_layout.addWidget(thumbnail_label)

        filename_label = QLabel(os.path.basename(image_path)[:15])
        filename_label.setStyleSheet("color: #ccc; font-size: 8px;")
        filename_label.setAlignment(Qt.AlignCenter)
        item_layout.addWidget(filename_label)

        item_data = {
            'path': image_path,
            'selected': False,
            'widget': item_widget,
            'thumbnail_label': thumbnail_label,
            'is_raw': self.image_processor.is_raw_format(image_path)
        }

        thumbnail_label.clicked.connect(
            lambda ctrl, shift: self._on_thumbnail_clicked(ctrl, shift, item_data)
        )

        self._update_item_style(item_data, is_loaded=False, is_error=False)

        self.image_items.append(item_data)
        return item_widget

    def _select_all_images(self):
        for item in self.image_items:
            self._set_item_selection(item, True)
        self._update_status_label()
        self._emit_selection_changed()

    def _select_no_images(self):
        for item in self.image_items:
            self._set_item_selection(item, False)
        self._update_status_label()
        self._emit_selection_changed()

    def _update_status_label(self):
        if not self.image_items:
            self.status_label.setText("No images loaded")
            return

        total_files = len(self.image_items)
        selected_count = sum(1 for item in self.image_items if self._get_item_selection(item))
        raw_count = sum(1 for item in self.image_items if item['is_raw'])
        regular_count = total_files - raw_count

        status_parts = []
        if regular_count > 0:
            status_parts.append(f"{regular_count} images")
        if raw_count > 0:
            status_parts.append(f"{raw_count} RAW files")

        status_text = ", ".join(status_parts) if status_parts else "No supported files"
        status_text += f" - {selected_count} selected"

        self.status_label.setText(status_text)

    def _emit_selection_changed(self):
        selected_images = self.get_selected_images()
        if self.signal_router:
            self.signal_router.emit('recon.selection_changed', {
                'selected_images': selected_images,
                'total_images': len(self.image_items)
            })

    def get_selected_images(self) -> List[str]:
        return [item['path'] for item in self.image_items if self._get_item_selection(item)]

    def clear_preview(self):
        for item in self.image_items:
            item['widget'].deleteLater()
        self.image_items = []
        self.last_single_selection_index = None
        self.status_label.setText("No images loaded")

        self.thumbnail_task_running = False
        self.converted_task_running = False
        self.thumbnail_completed = False
        self.converted_completed = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.image_items:
            self._relayout_items()

    def _relayout_items(self):
        cols = self._calculate_columns()

        for i, item in enumerate(self.image_items):
            row = i // cols
            col = i % cols
            self.grid_layout.addWidget(item['widget'], row, col)

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ImagePreviewPanel')