# core/worker_thread.py
from PySide6.QtCore import QThread, QObject
from typing import Dict, Optional
from logger import get_logger
import asyncio
import qasync

class Worker(QObject):
    """Worker class containing all API instances, runs in worker thread"""

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.apis: Dict[str, QObject] = {}
        self._create_apis()

    def _create_apis(self) -> Dict[str, QObject]:
        """Create all API instances"""
        from core.project import ProjectAPI
        from core.base_ops import BaseopsAPI
        from core.recon import ReconAPI
        from core.mesh import MeshAPI
        from core.render import RenderAPI
        from core.executor import ExecutorAPI
        from core.scene import SceneManager
        from core.pointcloud import PointcloudAPI

        self.apis = {
            'project': ProjectAPI(self.signal_router, self),
            'baseops': BaseopsAPI(self.signal_router, self),
            'recon': ReconAPI(self.signal_router, self),
            'mesh': MeshAPI(self.signal_router, self),
            'render': RenderAPI(self.signal_router, self),
            'executor': ExecutorAPI(self.signal_router, self),
            'scene': SceneManager(self.signal_router, self, self),
            'pointcloud': PointcloudAPI(self.signal_router, self, self)
        }

        return self.apis

    def initialize(self):
        """Initialize all APIs"""
        for name, api in self.apis.items():
            if hasattr(api, 'initialize'):
                api.initialize()
                self.logger.info(f"Initialized API: {name}")

        if self.signal_router:
            self.signal_router.emit('scene.request_sync', {})
            self.logger.info("Worker initialization completed")

    def get_api(self, name: str) -> Optional[QObject]:
        """Get API by name"""
        return self.apis.get(name)

    def cleanup(self):
        """Cleanup all APIs"""
        for api in self.apis.values():
            if hasattr(api, 'cleanup'):
                api.cleanup()
        self.apis.clear()


class WorkerThread(QThread):
    """Worker thread with qasync event loop"""

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.running = False
        self.worker = None

    def run(self):
        """Main thread execution with qasync event loop"""
        self.running = True
        self.logger.info("Worker thread started with qasync")

        self.worker = Worker(self.signal_router)

        loop = qasync.QEventLoop(self)
        asyncio.set_event_loop(loop)

        loop.call_soon(self.worker.initialize)

        loop.run_forever()

        self.logger.info("Worker thread stopped")

    def get_api(self, name: str) -> Optional[QObject]:
        """Get API by name"""
        if self.worker:
            return self.worker.get_api(name)
        return None

    def stop_thread(self):
        """Stop the worker thread"""
        self.running = False
        if self.worker:
            self.worker.cleanup()
        self.quit()
        self.wait()