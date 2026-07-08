# server/file_ops.py
import asyncio
import hashlib
import tempfile
import tarfile
import io
import os
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional

import aiofiles
import grpc

import meshwork_pb2
from utils import ChecksumUtils, get_workspace_path, validate_workspace_path


class FileOperations:
    """Core file transfer operations for both client and server"""

    @staticmethod
    def detect_file_type(path: Path) -> meshwork_pb2.FileType:
        """Detect if path is file or directory"""
        if path.is_file():
            return meshwork_pb2.FILE
        elif path.is_dir():
            return meshwork_pb2.DIRECTORY
        else:
            return meshwork_pb2.FILE_TYPE_UNSPECIFIED

    @staticmethod
    async def create_upload_chunks(local_path: Path, remote_path: str,
                                 chunk_size: int = 64*1024) -> AsyncIterator[meshwork_pb2.FileChunk]:
        """Create file chunks for upload streaming (supports files and directories)"""
        if not local_path.exists():
            raise FileNotFoundError(f"Local path not found: {local_path}")

        file_type = FileOperations.detect_file_type(local_path)

        if file_type == meshwork_pb2.FILE:
            # Handle single file upload
            async for chunk in FileOperations._create_file_chunks(local_path, remote_path, chunk_size):
                yield chunk
        elif file_type == meshwork_pb2.DIRECTORY:
            # Handle directory upload (tar streaming)
            async for chunk in FileOperations._create_directory_chunks(local_path, remote_path, chunk_size):
                yield chunk
        else:
            raise ValueError(f"Unsupported path type: {local_path}")

    @staticmethod
    async def _create_file_chunks(local_path: Path, remote_path: str,
                                chunk_size: int) -> AsyncIterator[meshwork_pb2.FileChunk]:
        """Create chunks for single file upload"""
        file_size = local_path.stat().st_size
        file_checksum = hashlib.md5()
        chunk_index = 0

        async with aiofiles.open(local_path, 'rb') as f:
            while True:
                chunk_data = await f.read(chunk_size)
                if not chunk_data:
                    break

                file_checksum.update(chunk_data)
                is_last = len(chunk_data) < chunk_size

                chunk = meshwork_pb2.FileChunk(
                    file_path=remote_path,
                    chunk_index=chunk_index,
                    total_size=file_size,
                    data=chunk_data,
                    is_last=is_last,
                    checksum=file_checksum.hexdigest() if is_last else "",
                    type=meshwork_pb2.FILE
                )

                yield chunk
                chunk_index += 1

                if is_last:
                    break

    @staticmethod
    async def _create_directory_chunks(local_path: Path, remote_path: str,
                                     chunk_size: int) -> AsyncIterator[meshwork_pb2.FileChunk]:
        """Create chunks for directory upload (tar streaming)"""
        tar_buffer = io.BytesIO()
        tar_checksum = hashlib.md5()
        chunk_index = 0

        # Create tar archive in memory
        with tarfile.open(fileobj=tar_buffer, mode='w|') as tar:
            for item in local_path.rglob('*'):
                if item.is_file():
                    arcname = str(item.relative_to(local_path))
                    tar.add(item, arcname=arcname)

        # Get tar data and reset buffer position
        tar_data = tar_buffer.getvalue()
        tar_size = len(tar_data)
        tar_checksum.update(tar_data)

        # Stream tar data in chunks
        offset = 0
        while offset < tar_size:
            chunk_data = tar_data[offset:offset + chunk_size]
            is_last = offset + len(chunk_data) >= tar_size

            chunk = meshwork_pb2.FileChunk(
                file_path=remote_path,
                chunk_index=chunk_index,
                total_size=tar_size,
                data=chunk_data,
                is_last=is_last,
                checksum=tar_checksum.hexdigest() if is_last else "",
                type=meshwork_pb2.DIRECTORY
            )

            yield chunk
            chunk_index += 1
            offset += len(chunk_data)

            if is_last:
                break

    @staticmethod
    async def handle_upload_stream(request_iterator, workspace: Optional[Path] = None) -> meshwork_pb2.FileUploadResponse:
        """Handle streaming file upload on server side (supports files and directories)"""
        if workspace is None:
            workspace = get_workspace_path()

        file_path = None
        file_type = None
        total_written = 0
        temp_file = None
        file_checksum = hashlib.md5()
        tar_buffer = io.BytesIO()

        try:
            async for chunk in request_iterator:
                if file_path is None:
                    # First chunk, setup file
                    file_path = chunk.file_path
                    file_type = chunk.type

                    # Validate path is within workspace
                    if not validate_workspace_path(workspace, file_path):
                        return meshwork_pb2.FileUploadResponse(
                            success=False,
                            message=f"Path outside workspace: {file_path}",
                            file_path="",
                            bytes_written=0,
                            type=file_type,
                            files_extracted=0
                        )

                if file_type == meshwork_pb2.FILE:
                    # Handle file upload
                    if temp_file is None:
                        target_path = workspace / file_path
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        temp_file = open(target_path, 'wb')

                    temp_file.write(chunk.data)
                    file_checksum.update(chunk.data)
                    total_written += len(chunk.data)

                elif file_type == meshwork_pb2.DIRECTORY:
                    # Handle directory upload (accumulate tar data)
                    tar_buffer.write(chunk.data)
                    file_checksum.update(chunk.data)
                    total_written += len(chunk.data)

                if chunk.is_last:
                    break

            if temp_file:
                temp_file.close()

            # Handle directory extraction
            if file_type == meshwork_pb2.DIRECTORY:
                files_extracted = await FileOperations._extract_tar_to_workspace(
                    tar_buffer, workspace, file_path
                )
            else:
                files_extracted = 1

            # Verify checksum if provided
            if chunk.checksum:
                calculated_checksum = file_checksum.hexdigest()
                if calculated_checksum != chunk.checksum:
                    # Clean up on checksum failure
                    if file_type == meshwork_pb2.FILE:
                        target_path = workspace / file_path
                        if target_path.exists():
                            target_path.unlink()
                    elif file_type == meshwork_pb2.DIRECTORY:
                        target_dir = workspace / file_path
                        if target_dir.exists():
                            shutil.rmtree(target_dir)

                    return meshwork_pb2.FileUploadResponse(
                        success=False,
                        message=f"Checksum mismatch: expected {chunk.checksum}, got {calculated_checksum}",
                        file_path="",
                        bytes_written=0,
                        type=file_type,
                        files_extracted=0
                    )

            return meshwork_pb2.FileUploadResponse(
                success=True,
                message="Upload successful",
                file_path=file_path,
                bytes_written=total_written,
                type=file_type,
                files_extracted=files_extracted
            )

        except Exception as e:
            if temp_file:
                temp_file.close()
            # Clean up on error
            if file_path:
                target_path = workspace / file_path
                if target_path.exists():
                    if target_path.is_file():
                        target_path.unlink()
                    else:
                        shutil.rmtree(target_path)

            return meshwork_pb2.FileUploadResponse(
                success=False,
                message=f"Upload failed: {str(e)}",
                file_path="",
                bytes_written=0,
                type=file_type or meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                files_extracted=0
            )

    @staticmethod
    async def _extract_tar_to_workspace(tar_buffer: io.BytesIO, workspace: Path, target_path: str) -> int:
        """Extract tar buffer to workspace directory"""
        tar_buffer.seek(0)
        target_dir = workspace / target_path
        target_dir.mkdir(parents=True, exist_ok=True)

        files_extracted = 0
        with tarfile.open(fileobj=tar_buffer, mode='r|') as tar:
            for member in tar:
                if member.isfile():
                    # Security check: ensure extracted path is within target directory
                    member_path = target_dir / member.name
                    if not str(member_path.resolve()).startswith(str(target_dir.resolve())):
                        raise ValueError(f"Unsafe path in tar: {member.name}")

                    tar.extract(member, target_dir)
                    files_extracted += 1

        return files_extracted

    @staticmethod
    async def create_download_stream(file_path: str, chunk_size: int = 64*1024,
                                   workspace: Optional[Path] = None) -> AsyncIterator[meshwork_pb2.FileDownloadResponse]:
        """Create download stream for server side (supports files and directories)"""
        if workspace is None:
            workspace = get_workspace_path()

        try:
            # Validate path is within workspace
            if not validate_workspace_path(workspace, file_path):
                yield meshwork_pb2.FileDownloadResponse(
                    file_path=file_path,
                    chunk_index=0,
                    total_size=0,
                    is_last=True,
                    type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                    error=f"Path outside workspace: {file_path}",
                    checksum=""
                )
                return

            full_path = workspace / file_path

            if not full_path.exists():
                yield meshwork_pb2.FileDownloadResponse(
                    file_path=file_path,
                    chunk_index=0,
                    total_size=0,
                    is_last=True,
                    type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                    error=f"File not found: {file_path}",
                    checksum=""
                )
                return

            file_type = FileOperations.detect_file_type(full_path)

            if file_type == meshwork_pb2.FILE:
                async for response in FileOperations._create_file_download_stream(
                    full_path, file_path, chunk_size
                ):
                    yield response
            elif file_type == meshwork_pb2.DIRECTORY:
                async for response in FileOperations._create_directory_download_stream(
                    full_path, file_path, chunk_size
                ):
                    yield response

        except Exception as e:
            yield meshwork_pb2.FileDownloadResponse(
                file_path=file_path,
                chunk_index=0,
                total_size=0,
                is_last=True,
                type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                error=f"Download failed: {str(e)}",
                checksum=""
            )

    @staticmethod
    async def _create_file_download_stream(full_path: Path, file_path: str, chunk_size: int) -> AsyncIterator[meshwork_pb2.FileDownloadResponse]:
        """Create download stream for single file"""
        file_size = full_path.stat().st_size
        calculated_checksum = ChecksumUtils.calculate_file_checksum(full_path)

        chunk_index = 0
        async with aiofiles.open(full_path, 'rb') as f:
            while True:
                chunk_data = await f.read(chunk_size)
                if not chunk_data:
                    break

                is_last = len(chunk_data) < chunk_size or await f.tell() >= file_size

                yield meshwork_pb2.FileDownloadResponse(
                    file_path=file_path,
                    chunk_index=chunk_index,
                    total_size=file_size,
                    is_last=is_last,
                    type=meshwork_pb2.FILE,
                    data=chunk_data,
                    checksum=calculated_checksum if is_last else ""
                )

                chunk_index += 1

                if is_last:
                    break

    @staticmethod
    async def _create_directory_download_stream(full_path: Path, file_path: str, chunk_size: int) -> AsyncIterator[meshwork_pb2.FileDownloadResponse]:
        """Create download stream for directory (tar streaming)"""
        tar_buffer = io.BytesIO()

        # Create tar archive in memory
        with tarfile.open(fileobj=tar_buffer, mode='w|') as tar:
            for item in full_path.rglob('*'):
                if item.is_file():
                    arcname = str(item.relative_to(full_path))
                    tar.add(item, arcname=arcname)

        # Get tar data and calculate checksum
        tar_data = tar_buffer.getvalue()
        tar_size = len(tar_data)
        tar_checksum = ChecksumUtils.calculate_data_checksum(tar_data)

        # Stream tar data in chunks
        chunk_index = 0
        offset = 0
        while offset < tar_size:
            chunk_data = tar_data[offset:offset + chunk_size]
            is_last = offset + len(chunk_data) >= tar_size

            yield meshwork_pb2.FileDownloadResponse(
                file_path=file_path,
                chunk_index=chunk_index,
                total_size=tar_size,
                is_last=is_last,
                type=meshwork_pb2.DIRECTORY,
                data=chunk_data,
                checksum=tar_checksum if is_last else ""
            )

            chunk_index += 1
            offset += len(chunk_data)

            if is_last:
                break

    @staticmethod
    async def save_download_stream(download_stream, local_path: Path) -> dict:
        """Save download stream to local file on client side (supports files and directories)"""
        local_path.parent.mkdir(parents=True, exist_ok=True)

        file_checksum = hashlib.md5()
        bytes_written = 0
        expected_checksum = None
        file_type = None
        tar_buffer = io.BytesIO()

        try:
            async for response in download_stream:
                if response.error:
                    return {
                        'success': False,
                        'error': response.error,
                        'bytes_written': bytes_written
                    }

                if file_type is None:
                    file_type = response.type

                if response.data:
                    if file_type == meshwork_pb2.FILE:
                        # Write file data directly
                        if bytes_written == 0:  # First chunk, open file
                            file_handle = await aiofiles.open(local_path, 'wb')

                        await file_handle.write(response.data)
                        file_checksum.update(response.data)
                        bytes_written += len(response.data)

                    elif file_type == meshwork_pb2.DIRECTORY:
                        # Accumulate tar data
                        tar_buffer.write(response.data)
                        file_checksum.update(response.data)
                        bytes_written += len(response.data)

                if response.is_last:
                    expected_checksum = response.checksum
                    break

            # Close file if it was opened
            if file_type == meshwork_pb2.FILE and bytes_written > 0:
                await file_handle.close()

            # Extract directory if it's a tar archive
            if file_type == meshwork_pb2.DIRECTORY:
                await FileOperations._extract_tar_to_local(tar_buffer, local_path)

            # Verify checksum
            if expected_checksum:
                calculated_checksum = file_checksum.hexdigest()
                if calculated_checksum != expected_checksum:
                    return {
                        'success': False,
                        'error': f"Checksum mismatch: expected {expected_checksum}, got {calculated_checksum}",
                        'bytes_written': bytes_written
                    }

            return {
                'success': True,
                'bytes_written': bytes_written,
                'checksum': file_checksum.hexdigest(),
                'type': file_type
            }

        except Exception as e:
            return {
                'success': False,
                'error': f"Save failed: {str(e)}",
                'bytes_written': bytes_written
            }

    @staticmethod
    async def _extract_tar_to_local(tar_buffer: io.BytesIO, local_path: Path):
        """Extract tar buffer to local directory"""
        tar_buffer.seek(0)
        local_path.mkdir(parents=True, exist_ok=True)

        with tarfile.open(fileobj=tar_buffer, mode='r|') as tar:
            for member in tar:
                if member.isfile():
                    # Security check: ensure extracted path is within target directory
                    member_path = local_path / member.name
                    if not str(member_path.resolve()).startswith(str(local_path.resolve())):
                        raise ValueError(f"Unsafe path in tar: {member.name}")

                    tar.extract(member, local_path)

    @staticmethod
    async def handle_delete_request(file_path: str, workspace: Optional[Path] = None) -> meshwork_pb2.FileDeleteResponse:
        """Handle file/directory deletion request"""
        if workspace is None:
            workspace = get_workspace_path()

        try:
            # Validate path is within workspace
            if not validate_workspace_path(workspace, file_path):
                return meshwork_pb2.FileDeleteResponse(
                    success=False,
                    message=f"Path outside workspace: {file_path}",
                    file_path=file_path,
                    type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                    files_deleted=0
                )

            full_path = workspace / file_path

            if not full_path.exists():
                return meshwork_pb2.FileDeleteResponse(
                    success=False,
                    message=f"Path not found: {file_path}",
                    file_path=file_path,
                    type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                    files_deleted=0
                )

            file_type = FileOperations.detect_file_type(full_path)
            files_deleted = 0

            if file_type == meshwork_pb2.FILE:
                full_path.unlink()
                files_deleted = 1
            elif file_type == meshwork_pb2.DIRECTORY:
                # Count files before deletion
                files_deleted = sum(1 for item in full_path.rglob('*') if item.is_file())
                shutil.rmtree(full_path)

            return meshwork_pb2.FileDeleteResponse(
                success=True,
                message=f"Successfully deleted {file_path}",
                file_path=file_path,
                type=file_type,
                files_deleted=files_deleted
            )

        except Exception as e:
            return meshwork_pb2.FileDeleteResponse(
                success=False,
                message=f"Delete failed: {str(e)}",
                file_path=file_path,
                type=meshwork_pb2.FILE_TYPE_UNSPECIFIED,
                files_deleted=0
            )