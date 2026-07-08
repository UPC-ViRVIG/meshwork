#!/usr/bin/env python3
# main.py
import sys
import os
import asyncio
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import after path setup
from config import get_config
from logger import get_logger, setup_logger
from gui.main import MainApplication
from gui.style_manager import get_style_manager

async def check_services():
    """Check service connectivity before starting GUI"""
    from server.client_api import MeshWorkClient

    config = get_config()
    services = {
        "blender": True,
        "colmap": False,
        "alicevision": False
    }

    for service, required in services.items():
        address = config.get("server").get("services", {}).get(service, "localhost")
        client = MeshWorkClient(service, address)
        result = await client.ping("startup_check")
        await client.close()

        if not result.get('success'):
            if required:
                error_msg = f"Cannot connect to {service} service: {result.get('error', 'Unknown error')}"
                print(f"Error: {error_msg}")

                # Show error dialog if possible
                app = QApplication.instance()
                if app is None:
                    app = QApplication([])
                QMessageBox.critical(None, "Service Connection Error", error_msg)

                return False
            else:
                print(f"Warning: {service} service not available - related features will be disabled")
        else:
            print(f"Info: {service} service connected successfully")

    return True

def main():
    """Main application entry point"""
    # Initialize configuration
    config = get_config()
    config.create_dirs()

    # Initialize logging
    logger = setup_logger()
    logger.info("Starting MeshWork application")

    # Check services before starting GUI
    services_ok = asyncio.run(check_services())
    if not services_ok:
        logger.error("Service connectivity check failed")
        return 1

    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("MeshWork")
    app.setApplicationVersion("0.0.1")
    app.setOrganizationName("MeshWork")

    # Apply theme
    style_manager = get_style_manager()
    style_manager.apply_theme(app)

    # Create and show main window
    main_window = MainApplication()
    main_window.show()

    logger.info("Application started successfully")

    # Run application
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())