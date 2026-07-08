# server/exec_ops.py
import asyncio
import os
import sys
import time
import tempfile
import shutil
import pty
import termios
import select
import threading
import queue
from dataclasses import dataclass
from pathlib import Path
from io import StringIO
from typing import AsyncIterator, Dict, Optional, List, Callable, Any

import meshwork_pb2
from utils import CompressionUtils, get_workspace_path


@dataclass
class PythonTask:
    """Encapsulates a Python execution task"""
    task_id: str
    script_content: str
    timeout: float
    future: asyncio.Future
    output_callback: Optional[Callable]
    created_at: float
    workspace: Path


class PythonExecutionQueue:
    """Manages Python script execution in main thread"""

    def __init__(self, max_queue_size: int = 100):
        self.task_queue = asyncio.Queue(maxsize=max_queue_size)
        self.running = False
        self.consumer_task = None
        self.task_counter = 0

    async def start(self):
        """Start the queue consumer"""
        if self.running:
            return
        self.running = True
        self.consumer_task = asyncio.create_task(self._consume_tasks())

    async def stop(self):
        """Stop the queue consumer"""
        self.running = False
        if self.consumer_task:
            self.consumer_task.cancel()
            await asyncio.gather(self.consumer_task, return_exceptions=True)

    async def submit_task(self, script_content: str, timeout: float = 0,
                         output_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Submit a Python execution task"""
        if not self.running:
            return {
                'success': False,
                'error': 'Python execution queue not running'
            }

        self.task_counter += 1
        task_id = f"py_{self.task_counter}_{int(time.time())}"
        future = asyncio.Future()

        task = PythonTask(
            task_id=task_id,
            script_content=script_content,
            timeout=timeout,
            future=future,
            output_callback=output_callback,
            created_at=time.time(),
            workspace=get_workspace_path()
        )

        if self.task_queue.full():
            return {
                'success': False,
                'error': 'Python execution queue is full'
            }

        await self.task_queue.put(task)

        # Wait for task completion
        if timeout > 0:
            result = await asyncio.wait_for(future, timeout=timeout)
        else:
            result = await future

        return result

    async def _consume_tasks(self):
        """Main consumer loop running in main thread"""
        while self.running:
            task = await self.task_queue.get()

            if task is None:  # Shutdown signal
                break

            await self._execute_task(task)

    async def _execute_task(self, task: PythonTask):
        """Execute a single Python task"""
        start_time = time.time()

        # Prepare execution environment
        script_globals = {
            '__builtins__': __builtins__,
            'workspace_path': str(task.workspace),
            'os': __import__('os'),
            'sys': __import__('sys'),
        }

        # Add Blender context if available
        try:
            import bpy
            script_globals['bpy'] = bpy
        except ImportError:
            pass

        # Capture stdout/stderr if callback provided
        original_stdout = None
        original_stderr = None

        if task.output_callback:
            original_stdout = sys.stdout
            original_stderr = sys.stderr

            # Create custom streams that call the callback
            sys.stdout = CallbackStream('stdout', task.output_callback)
            sys.stderr = CallbackStream('stderr', task.output_callback)

        result = {
            'success': False,
            'stdout': '',
            'stderr': '',
            'exit_info': {
                'exit_code': 1,
                'duration_ms': 0
            }
        }

        try:
            # Execute the script in main thread
            exec(task.script_content, script_globals)
            result['success'] = True
            result['exit_info']['exit_code'] = 0

        except Exception as e:
            error_msg = f"Python execution error: {str(e)}"
            result['error'] = error_msg
            if task.output_callback:
                await task.output_callback('stderr', error_msg.encode('utf-8'))

        finally:
            # Restore original streams
            if original_stdout:
                sys.stdout = original_stdout
            if original_stderr:
                sys.stderr = original_stderr

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            result['exit_info']['duration_ms'] = duration_ms

            # Set the result
            task.future.set_result(result)


class CallbackStream:
    """Custom stream that forwards writes to callback"""

    def __init__(self, stream_type: str, callback: Callable):
        self.stream_type = stream_type
        self.callback = callback

    def write(self, data: str):
        if data and self.callback:
            # Convert to bytes and call callback
            data_bytes = data.encode('utf-8')
            # Create task for async callback
            asyncio.create_task(self.callback(self.stream_type, data_bytes))
        return len(data)

    def flush(self):
        pass

    def writable(self):
        return True


class ExecutionOperations:
    """Core execution operations for both client and server"""

    @staticmethod
    def _pty_available() -> bool:
        """Check if PTY is available in current environment"""
        try:
            master, slave = pty.openpty()
            os.close(master)
            os.close(slave)
            return True
        except (OSError, AttributeError):
            return False

    @staticmethod
    def _should_use_pty(use_pty: Optional[bool]) -> bool:
        """Determine if PTY should be used based on user preference and availability"""
        if use_pty is False:
            return False
        elif use_pty is True:
            return ExecutionOperations._pty_available()
        else:
            # Auto-select: prefer PTY if available
            return ExecutionOperations._pty_available()

    @staticmethod
    def _clean_pty_output(data: bytes) -> bytes:
        """Clean PTY output by removing/converting control characters"""
        # Convert \r\n to \n, remove standalone \r
        text = data.decode('utf-8', errors='replace')
        # Handle common PTY control sequences
        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        return text.encode('utf-8')

    @staticmethod
    async def execute_command(argv: List[str], cwd: str = "", env: Optional[Dict[str, str]] = None,
                            timeout: float = 0, compression_config: Optional[Dict] = None,
                            use_pty: Optional[bool] = None, pty_rows: int = 24, pty_cols: int = 80) -> AsyncIterator[meshwork_pb2.OutputFrame]:
        """Execute shell command and stream output with PTY support"""

        # Determine execution mode
        actual_use_pty = ExecutionOperations._should_use_pty(use_pty)

        if actual_use_pty:
            print(f"Using PTY mode for real-time output")
            async for frame in ExecutionOperations._execute_command_pty(
                argv, cwd, env, timeout, compression_config, pty_rows, pty_cols
            ):
                yield frame
        else:
            if use_pty is True:
                print("PTY requested but not available, falling back to subprocess mode")
            async for frame in ExecutionOperations._execute_command_subprocess(
                argv, cwd, env, timeout, compression_config
            ):
                yield frame

    @staticmethod
    async def _execute_command_pty(argv: List[str], cwd: str = "", env: Optional[Dict[str, str]] = None,
                                 timeout: float = 0, compression_config: Optional[Dict] = None,
                                 pty_rows: int = 24, pty_cols: int = 80) -> AsyncIterator[meshwork_pb2.OutputFrame]:
        """Execute command using PTY for real-time output"""
        seq = 0
        start_time = time.time()
        total_stdout = 0
        total_stderr = 0

        # Setup working directory
        workspace = get_workspace_path()
        if cwd:
            work_dir = workspace / cwd
        else:
            work_dir = workspace

        # Setup environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Create PTY
        try:
            master, slave = pty.openpty()

            # Set terminal size
            try:
                winsize = termios.struct_winsize()
                winsize.ws_row = pty_rows
                winsize.ws_col = pty_cols
                termios.tcsetwinsize(slave, winsize)
            except (AttributeError, OSError):
                # Some systems may not support setting window size
                pass

        except OSError as e:
            # PTY creation failed, yield error
            yield ExecutionOperations._create_exit_frame(
                seq, start_time, -1, 0, total_stdout, total_stderr, False
            )
            return

        # Start process with PTY
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=slave,
                stderr=asyncio.subprocess.PIPE,  # Keep stderr separate
                cwd=str(work_dir),
                env=process_env
            )
            os.close(slave)  # Close slave in parent process
        except Exception as e:
            os.close(master)
            os.close(slave)
            yield ExecutionOperations._create_exit_frame(
                seq, start_time, -1, 0, total_stdout, total_stderr, False
            )
            return

        # Create output queue for multiplexing
        output_queue = asyncio.Queue()

        # Start concurrent readers
        pty_task = asyncio.create_task(
            ExecutionOperations._read_pty_to_queue(master, output_queue)
        )
        stderr_task = asyncio.create_task(
            ExecutionOperations._read_stderr_to_queue(process.stderr, output_queue)
        )

        try:
            # Read and yield frames in real-time
            while True:
                # Check if process finished
                if process.returncode is not None:
                    break

                try:
                    # Get output with timeout
                    output_data = await asyncio.wait_for(output_queue.get(), timeout=0.1)
                    stream_type, data = output_data

                    if stream_type == 'stdout':
                        cleaned_data = ExecutionOperations._clean_pty_output(data)
                        if cleaned_data:
                            frame = ExecutionOperations._create_output_frame(
                                seq, meshwork_pb2.STDOUT, cleaned_data, compression_config
                            )
                            yield frame
                            total_stdout += len(cleaned_data)
                            seq += 1

                    elif stream_type == 'stderr':
                        frame = ExecutionOperations._create_output_frame(
                            seq, meshwork_pb2.STDERR, data, compression_config
                        )
                        yield frame
                        total_stderr += len(data)
                        seq += 1

                except asyncio.TimeoutError:
                    # No output available, continue checking
                    continue

            # Wait for process completion with timeout
            try:
                if timeout > 0:
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                    timed_out = False
                else:
                    await process.wait()
                    timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                timed_out = True

            # Get any remaining output
            while not output_queue.empty():
                try:
                    output_data = output_queue.get_nowait()
                    stream_type, data = output_data

                    if stream_type == 'stdout':
                        cleaned_data = ExecutionOperations._clean_pty_output(data)
                        if cleaned_data:
                            frame = ExecutionOperations._create_output_frame(
                                seq, meshwork_pb2.STDOUT, cleaned_data, compression_config
                            )
                            yield frame
                            total_stdout += len(cleaned_data)
                            seq += 1

                    elif stream_type == 'stderr':
                        frame = ExecutionOperations._create_output_frame(
                            seq, meshwork_pb2.STDERR, data, compression_config
                        )
                        yield frame
                        total_stderr += len(data)
                        seq += 1
                except asyncio.QueueEmpty:
                    break

        finally:
            # Cancel tasks and cleanup
            pty_task.cancel()
            stderr_task.cancel()

            try:
                await pty_task
            except asyncio.CancelledError:
                pass

            try:
                await stderr_task
            except asyncio.CancelledError:
                pass

            try:
                os.close(master)
            except OSError:
                pass

        # Send EXIT frame with correct exit code
        exit_code = process.returncode if process.returncode is not None else -1
        yield ExecutionOperations._create_exit_frame(
            seq, start_time, exit_code, 0,
            total_stdout, total_stderr, timed_out
        )

    @staticmethod
    async def _read_pty_to_queue(master_fd: int, queue: asyncio.Queue):
        """Read from PTY master and put data in queue"""
        loop = asyncio.get_event_loop()

        def read_ready():
            try:
                data = os.read(master_fd, 8192)
                if data:
                    loop.call_soon_threadsafe(queue.put_nowait, ('stdout', data))
            except OSError:
                pass  # PTY closed

        try:
            loop.add_reader(master_fd, read_ready)

            # Keep the reader active until cancelled
            while True:
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                loop.remove_reader(master_fd)
            except (ValueError, OSError):
                pass

    @staticmethod
    async def _read_stderr_to_queue(stderr_stream, queue: asyncio.Queue):
        """Read from stderr stream and put data in queue"""
        try:
            while True:
                chunk = await stderr_stream.read(8192)
                if not chunk:
                    break
                await queue.put(('stderr', chunk))
        except (asyncio.CancelledError, Exception):
            pass

    @staticmethod
    async def _execute_command_subprocess(argv: List[str], cwd: str = "", env: Optional[Dict[str, str]] = None,
                                        timeout: float = 0, compression_config: Optional[Dict] = None) -> AsyncIterator[meshwork_pb2.OutputFrame]:
        """Execute command using traditional subprocess (simplified, no stdbuf)"""
        seq = 0
        start_time = time.time()
        total_stdout = 0
        total_stderr = 0

        # Setup working directory
        workspace = get_workspace_path()
        if cwd:
            work_dir = workspace / cwd
        else:
            work_dir = workspace

        # Setup environment
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        # Start process (simplified - no stdbuf wrapping)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                env=process_env
            )
        except Exception as e:
            yield ExecutionOperations._create_exit_frame(
                seq, start_time, -1, 0, total_stdout, total_stderr, False
            )
            return

        # Read stdout and stderr concurrently
        stdout_task = asyncio.create_task(ExecutionOperations._read_stream(process.stdout))
        stderr_task = asyncio.create_task(ExecutionOperations._read_stream(process.stderr))

        # Wait for completion with timeout
        try:
            if timeout > 0:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                timed_out = False
            else:
                await process.wait()
                timed_out = False
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            timed_out = True

        # Get all output
        stdout_data = await stdout_task
        stderr_data = await stderr_task

        # Send stdout frames
        for data in stdout_data:
            frame = ExecutionOperations._create_output_frame(
                seq, meshwork_pb2.STDOUT, data, compression_config
            )
            yield frame
            total_stdout += len(data)
            seq += 1

        # Send stderr frames
        for data in stderr_data:
            frame = ExecutionOperations._create_output_frame(
                seq, meshwork_pb2.STDERR, data, compression_config
            )
            yield frame
            total_stderr += len(data)
            seq += 1

        # Send EXIT frame
        yield ExecutionOperations._create_exit_frame(
            seq, start_time, process.returncode, 0,
            total_stdout, total_stderr, timed_out
        )

    @staticmethod
    async def execute_python_direct(script_content: str, timeout: float = 0,
                                  compression_config: Optional[Dict] = None,
                                  python_queue: Optional[PythonExecutionQueue] = None) -> AsyncIterator[meshwork_pb2.OutputFrame]:
        """Execute Python script using the main thread queue"""
        seq = 0
        start_time = time.time()
        total_stdout = 0
        total_stderr = 0

        if python_queue is None:
            # Fallback to subprocess mode if no queue available
            async for frame in ExecutionOperations.execute_python_subprocess(
                script_content, timeout, compression_config
            ):
                yield frame
            return

        # Create output callback to capture and stream output
        output_frames = []

        async def output_callback(stream_type: str, data: bytes):
            nonlocal seq, total_stdout, total_stderr

            stream_enum = meshwork_pb2.STDOUT if stream_type == 'stdout' else meshwork_pb2.STDERR

            frame = ExecutionOperations._create_output_frame(
                seq, stream_enum, data, compression_config, python_exec=True
            )

            output_frames.append(frame)

            if stream_type == 'stdout':
                total_stdout += len(data)
            else:
                total_stderr += len(data)

            seq += 1

        # Submit task to queue and wait for completion
        result = await python_queue.submit_task(
            script_content=script_content,
            timeout=timeout,
            output_callback=output_callback
        )

        # Yield all collected output frames
        for frame in output_frames:
            yield frame

        # Determine exit code
        exit_code = 0 if result.get('success', False) else 1
        timed_out = 'timeout' in result.get('error', '').lower()

        # Send exit frame
        yield ExecutionOperations._create_exit_frame(
            seq, start_time, exit_code, 0,
            total_stdout, total_stderr, timed_out, python_exec=True
        )

    @staticmethod
    async def execute_python_subprocess(script_content: str, timeout: float = 0,
                                      compression_config: Optional[Dict] = None) -> AsyncIterator[meshwork_pb2.OutputFrame]:
        """Execute Python script via subprocess"""
        workspace = get_workspace_path()
        script_file = workspace / f"temp_script_{int(time.time())}.py"

        try:
            # Write script content to file
            with open(script_file, 'w', encoding='utf-8') as f:
                f.write(script_content)

            # Execute python script
            argv = ["python3", str(script_file)]
            async for frame in ExecutionOperations.execute_command(
                argv, "", None, timeout, compression_config
            ):
                # Mark as python execution
                frame.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                frame.working_dir = str(workspace)
                yield frame

        finally:
            # Clean up temporary script file
            if script_file.exists():
                script_file.unlink()

    @staticmethod
    async def _read_stream(stream):
        """Read all data from stream"""
        chunks = []
        while True:
            try:
                chunk = await stream.read(8192)
                if not chunk:
                    break
                chunks.append(chunk)
            except:
                break
        return chunks

    @staticmethod
    def _create_output_frame(seq: int, stream_type: int, data: bytes,
                           compression_config: Optional[Dict] = None,
                           python_exec: bool = False) -> meshwork_pb2.OutputFrame:
        """Create output frame with optional compression"""
        frame = meshwork_pb2.OutputFrame()
        frame.seq = seq
        frame.ts.GetCurrentTime()
        frame.stream = stream_type
        frame.raw_len = len(data)

        # Apply compression if configured
        if compression_config:
            preferred_codec = compression_config.get('preferred_codec', meshwork_pb2.CODEC_NONE)
            threshold = compression_config.get('compress_threshold', 1024)
            compressed_data, codec = CompressionUtils.compress_if_needed(data, threshold, preferred_codec)
            frame.codec = codec
            frame.data = compressed_data
        else:
            frame.codec = meshwork_pb2.CODEC_NONE
            frame.data = data

        return frame

    @staticmethod
    def _create_exit_frame(seq: int, start_time: float, exit_code: int, signal_num: int,
                         total_stdout: int, total_stderr: int, timed_out: bool,
                         python_exec: bool = False) -> meshwork_pb2.OutputFrame:
        """Create exit frame"""
        frame = meshwork_pb2.OutputFrame()
        frame.seq = seq
        frame.ts.GetCurrentTime()
        frame.stream = meshwork_pb2.EXIT
        frame.codec = meshwork_pb2.CODEC_NONE
        frame.raw_len = 0
        frame.data = b""

        frame.exit_code = exit_code
        frame.signal = signal_num
        frame.total_stdout = total_stdout
        frame.total_stderr = total_stderr

        # Set duration
        duration_ms = int((time.time() - start_time) * 1000)
        frame.duration.seconds = duration_ms // 1000
        frame.duration.nanos = (duration_ms % 1000) * 1000000
        frame.timed_out = timed_out

        # Add Python-specific info
        if python_exec:
            try:
                import bpy
                frame.python_version = f"blender-python-{bpy.app.version_string}"
            except ImportError:
                frame.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            frame.working_dir = str(get_workspace_path())

        return frame


class OutputProcessor:
    """Process output frames from execution streams"""

    @staticmethod
    async def process_output_stream(output_stream, callback=None):
        """Process output stream and optionally call callback for each frame"""
        total_stdout = 0
        total_stderr = 0
        exit_info = None

        async for frame in output_stream:
            if frame.stream == meshwork_pb2.STDOUT:
                data = CompressionUtils.decompress_if_needed(frame.data, frame.codec)
                if callback:
                    await callback('stdout', data)
                else:
                    sys.stdout.write(data.decode('utf-8', errors='replace'))
                    sys.stdout.flush()
                total_stdout += frame.raw_len

            elif frame.stream == meshwork_pb2.STDERR:
                data = CompressionUtils.decompress_if_needed(frame.data, frame.codec)
                if callback:
                    await callback('stderr', data)
                else:
                    sys.stderr.write(data.decode('utf-8', errors='replace'))
                    sys.stderr.flush()
                total_stderr += frame.raw_len

            elif frame.stream == meshwork_pb2.EXIT:
                exit_info = {
                    'exit_code': frame.exit_code,
                    'signal': frame.signal,
                    'duration_ms': frame.duration.seconds * 1000 + frame.duration.nanos // 1000000,
                    'timed_out': frame.timed_out,
                    'python_version': frame.python_version if frame.python_version else None,
                    'working_dir': frame.working_dir if frame.working_dir else None
                }

        return {
            'total_stdout': total_stdout,
            'total_stderr': total_stderr,
            'exit_info': exit_info
        }