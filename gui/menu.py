# gui/menu.py
from PySide6.QtWidgets import QMainWindow, QMenu, QFileDialog, QMessageBox
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QIcon, QKeySequence, QAction
from typing import Dict, List, Optional, Any, Callable, Union
from logger import get_logger
from gui.win_recon import ReconWindow

class MenuBuilder(QObject):

    action_triggered = Signal(str)

    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.main_window = main_window
        self.logger = get_logger()

        self.menus: Dict[str, QMenu] = {}
        self.actions: Dict[str, QAction] = {}

    def create_menu(self, menu_id: str, title: str, parent_id: Optional[str] = None) -> QMenu:
        if menu_id in self.menus:
            return self.menus[menu_id]

        if parent_id is None:
            menu = self.main_window.menuBar().addMenu(title)
        else:
            if parent_id not in self.menus:
                self.logger.warning(f"Parent menu not found: {parent_id}")
                return None
            menu = self.menus[parent_id].addMenu(title)

        self.menus[menu_id] = menu
        return menu

    def add_action(self, action_id: str, menu_id: str, text: str,
                  callback: Optional[Callable] = None,
                  shortcut: Optional[Union[QKeySequence, str]] = None,
                  icon: Optional[QIcon] = None,
                  checkable: bool = False,
                  status_tip: Optional[str] = None) -> QAction:
        if menu_id not in self.menus:
            self.logger.warning(f"Menu not found: {menu_id}")
            return None

        action = QAction(text, self.main_window)

        if shortcut is not None:
            action.setShortcut(shortcut)
        if icon is not None:
            action.setIcon(icon)
        if status_tip is not None:
            action.setStatusTip(status_tip)
        if checkable:
            action.setCheckable(True)

        if callback is not None:
            action.triggered.connect(callback)

        self.menus[menu_id].addAction(action)
        self.actions[action_id] = action

        return action

    def add_separator(self, menu_id: str):
        if menu_id in self.menus:
            self.menus[menu_id].addSeparator()

    def get_action(self, action_id: str) -> Optional[QAction]:
        return self.actions.get(action_id)

    def get_menu(self, menu_id: str) -> Optional[QMenu]:
        return self.menus.get(menu_id)


class MenuHandler(QObject):

    def __init__(self, main_window, signal_router=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.signal_router = signal_router
        self.logger = get_logger()
        self.recon_window_instance = None

    def on_file_new(self):
        self.main_window.project_state.new_project()

    def on_file_open(self):
        self.main_window.project_state.open_project()

    def on_file_save(self):
        self.main_window.project_state.save_project()

    def on_file_save_as(self):
        self.main_window.project_state.save_project_as()

    def on_file_import(self):
        self.main_window.project_state.import_file()

    def on_file_export(self):
        self.main_window.project_state.export_file()

    def on_edit_undo(self):
        if self.signal_router:
            self.signal_router.emit('baseops.do_undo', {})

    def on_edit_redo(self):
        if self.signal_router:
            self.signal_router.emit('baseops.do_redo', {})

    def on_edit_select_all(self):
        if self.signal_router:
            self.signal_router.emit('scene.do_select_all', {})

    def on_edit_deselect_all(self):
        if self.signal_router:
            self.signal_router.emit('scene.do_clear_selection', {})

    def on_edit_delete(self):
        if self.signal_router:
            self.signal_router.emit('scene.do_remove_object', {})

    def on_add_cube(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'cube',
                'params': {'size': 2.0}
            })

    def on_add_sphere(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'sphere',
                'params': {'radius': 1.0}
            })

    def on_add_cylinder(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'cylinder',
                'params': {'radius': 1.0, 'depth': 2.0}
            })

    def on_add_cone(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'cone',
                'params': {'radius1': 1.0, 'radius2': 0.0, 'depth': 2.0}
            })

    def on_add_torus(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'torus',
                'params': {'major_radius': 1.0, 'minor_radius': 0.25}
            })

    def on_add_monkey(self):
        if self.signal_router:
            self.signal_router.emit('scene.add_primitive', {
                'type': 'monkey',
                'params': {'size': 2.0}
            })

    def on_tools_reconstruction(self):
        if self.recon_window_instance is None:
            self.recon_window_instance = ReconWindow(self.signal_router, self.main_window)

        self.recon_window_instance.show()
        self.recon_window_instance.raise_()
        self.recon_window_instance.activateWindow()

    def cleanup_recon_window(self):
        if self.recon_window_instance:
            self.recon_window_instance.real_close()
            self.recon_window_instance = None

    def on_view_reset_layout(self):
        if self.signal_router:
            self.signal_router.emit('view.reset_layout', {})

    def on_help_about(self):
        try:
            from gui.dialog_about import AboutDialog
            dialog = AboutDialog(self.main_window)
            dialog.exec()
        except ImportError:
            QMessageBox.about(self.main_window, "About MeshWork",
                            "MeshWork v1.0.0\n\n3D Mesh Processing and Reconstruction Tool")


class MenuManager(QObject):

    def __init__(self, main_window, signal_router=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.signal_router = signal_router

        self.builder = MenuBuilder(main_window)
        self.handler = MenuHandler(main_window, signal_router, self)

        self.logger = get_logger()

    def setup_menus(self):
        self._setup_file_menu()
        self._setup_edit_menu()
        self._setup_add_menu()
        self._setup_view_menu()
        self._setup_tools_menu()
        self._setup_help_menu()

    def _setup_file_menu(self):
        self.builder.create_menu("file", "&File")
        self.builder.add_action("file_new", "file", "&New",
                               self.handler.on_file_new, QKeySequence.New,
                               status_tip="Create a new project")
        self.builder.add_action("file_open", "file", "&Open...",
                               self.handler.on_file_open, QKeySequence.Open,
                               status_tip="Open an existing project")
        self.builder.add_separator("file")
        self.builder.add_action("file_save", "file", "&Save",
                               self.handler.on_file_save, QKeySequence.Save,
                               status_tip="Save current project")
        self.builder.add_action("file_save_as", "file", "Save &As...",
                               self.handler.on_file_save_as, QKeySequence.SaveAs,
                               status_tip="Save project with new name")
        self.builder.add_separator("file")
        self.builder.add_action("file_import", "file", "&Import...",
                               self.handler.on_file_import, "Ctrl+I",
                               status_tip="Import mesh file")
        self.builder.add_action("file_export", "file", "&Export...",
                               self.handler.on_file_export, "Ctrl+E",
                               status_tip="Export selected objects")
        self.builder.add_separator("file")
        self.builder.add_action("file_exit", "file", "E&xit",
                               self.main_window.close, QKeySequence.Quit,
                               status_tip="Exit application")

    def _setup_edit_menu(self):
        self.builder.create_menu("edit", "&Edit")
        self.builder.add_action("edit_undo", "edit", "&Undo",
                               self.handler.on_edit_undo, QKeySequence.Undo,
                               status_tip="Undo last operation")
        self.builder.add_action("edit_redo", "edit", "&Redo",
                               self.handler.on_edit_redo, QKeySequence.Redo,
                               status_tip="Redo last undone operation")
        self.builder.add_separator("edit")
        self.builder.add_action("edit_select_all", "edit", "Select &All",
                               self.handler.on_edit_select_all, QKeySequence.SelectAll,
                               status_tip="Select all objects")
        self.builder.add_action("edit_deselect_all", "edit", "&Deselect All",
                               self.handler.on_edit_deselect_all, "Ctrl+D",
                               status_tip="Deselect all objects")
        self.builder.add_separator("edit")
        self.builder.add_action("edit_delete", "edit", "&Delete",
                               self.handler.on_edit_delete, QKeySequence.Delete,
                               status_tip="Delete selected objects")

    def _setup_add_menu(self):
        self.builder.create_menu("add", "&Add")
        self.builder.add_action("add_cube", "add", "&Cube",
                               self.handler.on_add_cube, "Shift+A, C",
                               status_tip="Add cube primitive")
        self.builder.add_action("add_sphere", "add", "&Sphere",
                               self.handler.on_add_sphere, "Shift+A, S",
                               status_tip="Add UV sphere primitive")
        self.builder.add_action("add_cylinder", "add", "C&ylinder",
                               self.handler.on_add_cylinder, "Shift+A, Y",
                               status_tip="Add cylinder primitive")
        self.builder.add_action("add_cone", "add", "C&one",
                               self.handler.on_add_cone, "Shift+A, O",
                               status_tip="Add cone primitive")
        self.builder.add_action("add_torus", "add", "&Torus",
                               self.handler.on_add_torus, "Shift+A, T",
                               status_tip="Add torus primitive")
        self.builder.add_action("add_monkey", "add", "&Monkey",
                               self.handler.on_add_monkey, "Shift+A, M",
                               status_tip="Add monkey head primitive")

    def _setup_view_menu(self):
        self.builder.create_menu("view", "&View")
        self.builder.add_action("view_reset_layout", "view", "&Reset Layout",
                               self.handler.on_view_reset_layout, "Ctrl+Alt+R",
                               status_tip="Reset GUI layout to default")

    def _setup_tools_menu(self):
        self.builder.create_menu("tools", "&Tools")
        self.builder.add_action("tools_reconstruction", "tools", "3D &Reconstruction...",
                               self.handler.on_tools_reconstruction, "Ctrl+R",
                               status_tip="Start 3D reconstruction")

    def _setup_help_menu(self):
        self.builder.create_menu("help", "&Help")
        self.builder.add_action("help_about", "help", "&About",
                               self.handler.on_help_about, None,
                               status_tip="About MeshWork")

    def get_action(self, action_id: str) -> Optional[QAction]:
        return self.builder.get_action(action_id)

    def cleanup(self):
        pass