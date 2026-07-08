# gui/__init__.py
from .main import MainApplication
from .menu import MenuManager, MenuBuilder, MenuHandler
from .view import View, ViewManager
from .render import SceneRenderer, RenderObjectData
from .script import ScriptArea, ScriptEditor, ScriptConsole
from .dock_manager import DockManager
from .style_manager import StyleManager, get_style_manager
from .project_state import ProjectState

# Panels
from .panel_tools import ToolsPanel, ToolsController
from .panel_scene import ScenePanel, SceneController
from .panel_material import MaterialPanel
from .panel_render import RenderPanel

# Dialogs
from .dialog_about import AboutDialog
from .win_recon import ReconWindow

# Image Management
from .image_manager import ImageProcessor, ImagePreviewPanel

__all__ = [
    # Main application
    'MainApplication',

    # Core GUI components
    'MenuManager', 'MenuBuilder', 'MenuHandler',
    'View', 'ViewManager',
    'SceneRenderer', 'RenderObjectData',
    'ScriptArea', 'ScriptEditor', 'ScriptConsole',
    'DockManager',
    'StyleManager', 'get_style_manager',
    'ProjectState',

    # Panels
    'ToolsPanel', 'ToolsController',
    'ScenePanel', 'SceneController',
    'MaterialPanel',
    'RenderPanel',

    # Dialogs
    'AboutDialog',
    'ReconWindow',

    # Image Management
    'ImageProcessor', 'ImagePreviewPanel'
]