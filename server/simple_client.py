#!/usr/bin/env python3
# server/simple_client.py
import asyncio
import sys
import os
import argparse
import shlex
import shutil
from pathlib import Path

from client_api import MeshWorkClient, ProgressReporter
from utils import format_duration, format_bytes


def type_to_string(file_type):
    """Convert protobuf file type enum to string"""
    if isinstance(file_type, str):
        return file_type.lower()
    elif file_type == 0:
        return 'unspecified'
    elif file_type == 1:
        return 'file'
    elif file_type == 2:
        return 'directory'
    else:
        return f'unknown({file_type})'


class InteractiveSession:
    """Base class for interactive sessions"""

    def __init__(self, client: MeshWorkClient, service_name: str):
        self.client = client
        self.service_name = service_name
        self.cwd = ""
        self.timeout = 0
        self.env_vars = {}

    async def show_status(self):
        """Show connection and session status"""
        print(f"Service: {self.service_name}")
        print(f"Address: {self.client.address}")
        print(f"Connected: {self.client._connected}")
        print(f"Working directory: {self.cwd or '/workspace'}")
        print(f"Timeout: {self.timeout}s" if self.timeout > 0 else "Timeout: disabled")
        print(f"Environment variables: {len(self.env_vars)}")
        for key, value in self.env_vars.items():
            print(f"  {key}={value}")

    def show_base_help(self):
        """Show base interactive commands help"""
        print("Commands:")
        print("  !cwd <path>           Change working directory")
        print("  !timeout <seconds>    Set timeout")
        print("  !envset <key>=<value> Set environment variable")
        print("  !env                  Show environment")
        print("  !status               Show status")
        print("  help                  Show help")
        print("  quit/exit/Ctrl+D      Exit")

    async def handle_special_command(self, command: str) -> bool:
        """Handle special ! commands, return True if handled"""
        if command.startswith("!cwd "):
            self.cwd = command[5:].strip()
            print(f"Working directory changed to: /workspace/{self.cwd}" if self.cwd else "/workspace")
            return True

        elif command.startswith("!timeout "):
            try:
                self.timeout = float(command[9:].strip())
                print(f"Timeout set to: {self.timeout}s" if self.timeout > 0 else "Timeout disabled")
            except ValueError:
                print("Invalid timeout value")
            return True

        elif command.startswith("!envset "):
            env_str = command[8:].strip()
            if "=" in env_str:
                key, value = env_str.split("=", 1)
                self.env_vars[key] = value
                print(f"Environment variable set: {key}={value}")
            else:
                print("Usage: !envset <key>=<value>")
            return True

        elif command == "!env":
            if self.env_vars:
                print("Current environment variables:")
                for key, value in self.env_vars.items():
                    print(f"  {key}={value}")
            else:
                print("No custom environment variables set")
            return True

        elif command == "!status":
            await self.show_status()
            return True

        return False


class PythonInteractiveSession(InteractiveSession):
    """Interactive Python execution session"""

    def _is_complete_statement(self, code: str) -> bool:
        """Check if Python code is a complete statement"""
        try:
            compile(code, '<string>', 'exec')
            return True
        except SyntaxError as e:
            # Check if it's an incomplete statement
            if "unexpected EOF while parsing" in str(e) or "expected an indented block" in str(e):
                return False
            # Other syntax errors should be reported
            return True
        except:
            return True

    async def run(self):
        """Run Python interactive mode"""
        print(f"Python Interactive Mode - type 'help' for commands, 'quit' to exit")
        print("For multi-line input, end with an empty line")
        print()

        while True:
            try:
                # Multi-line input support
                lines = []
                prompt = f"{self.service_name}-python> "

                while True:
                    try:
                        if lines:
                            line = input("... ")
                        else:
                            line = input(prompt)
                    except EOFError:
                        # Support Ctrl+D
                        print()
                        return

                    if not line.strip() and lines:
                        # Empty line ends multi-line input
                        break

                    lines.append(line)

                    # Check for single-line completion
                    if len(lines) == 1:
                        current_code = line.strip()

                        if not current_code:
                            continue

                        if current_code in ["quit", "exit"]:
                            return

                        if current_code == "help":
                            self.show_help()
                            lines = []
                            continue

                        if await self.handle_special_command(current_code):
                            lines = []
                            continue

                        # Check if single line is complete
                        if self._is_complete_statement(current_code):
                            break

                # Execute accumulated code
                if lines:
                    script = '\n'.join(lines)
                    await self._execute_python(script)

            except KeyboardInterrupt:
                print("\nKeyboardInterrupt")
                print("Use 'quit', 'exit', or Ctrl+D to exit")
            except Exception as e:
                print(f"Error: {e}")

    def show_help(self):
        """Show Python interactive help"""
        print("Python mode: Execute Python scripts")
        self.show_base_help()

    async def _execute_python(self, script: str):
        """Execute Python script"""
        try:
            # Real-time output callback with color support
            def output_callback(stream_type: str, text: str):
                """Print output in real time with color coding"""
                if stream_type == 'stdout':
                    print(text, end='')
                elif stream_type == 'stderr':
                    # Print stderr in red
                    print(f'\033[31m{text}\033[0m', end='')
                sys.stdout.flush()

            result = await self.client.execute_python(
                script_content=script,
                timeout=self.timeout,
                output_callback=output_callback
            )

            if not result['success']:
                print(f"Execution failed: {result.get('error', 'Unknown error')}")

            # Print execution summary
            if 'exit_info' in result and result['exit_info']:
                exit_info = result['exit_info']
                if exit_info['exit_code'] != 0:
                    print(f"Exit code: {exit_info['exit_code']}")

        except Exception as e:
            print(f"Execution error: {e}")


class CommandInteractiveSession(InteractiveSession):
    """Interactive command execution session (argv mode)"""

    async def run(self):
        """Run command interactive mode"""
        print(f"Command Interactive Mode (argv) - type 'help' for commands, 'quit' to exit")
        print("Commands are parsed as individual arguments (safe mode)")
        print()

        while True:
            try:
                try:
                    command = input(f"{self.service_name}> ").strip()
                except EOFError:
                    # Support Ctrl+D
                    print()
                    break

                if not command:
                    continue

                if command in ["quit", "exit"]:
                    break

                elif command == "help":
                    self.show_help()

                elif await self.handle_special_command(command):
                    continue

                else:
                    # Parse command into argv
                    await self._execute_command_argv(command)

            except KeyboardInterrupt:
                print("\nUse 'quit', 'exit', or Ctrl+D to exit")
            except Exception as e:
                print(f"Error: {e}")

    def show_help(self):
        """Show command interactive help"""
        print("Command mode (argv): Safe parsing, no shell features")
        self.show_base_help()

    async def _execute_command_argv(self, command_str: str):
        """Execute command by parsing into argv"""
        try:
            # Parse command into argv using shlex
            try:
                argv = shlex.split(command_str)
            except ValueError as e:
                print(f"Command parsing error: {e}")
                print("Tip: Check quotes and escaping. For complex shell commands, use --command-pty")
                return

            if not argv:
                print("Empty command")
                return

            # Check if command exists
            if not shutil.which(argv[0]):
                print(f"Command not found: {argv[0]}")
                return

            # Real-time output callback with color support
            def output_callback(stream_type: str, text: str):
                """Print output in real time with color coding"""
                if stream_type == 'stdout':
                    print(text, end='')
                elif stream_type == 'stderr':
                    # Print stderr in red
                    print(f'\033[31m{text}\033[0m', end='')
                sys.stdout.flush()

            result = await self.client.execute_command(
                command=argv,
                cwd=self.cwd,
                env=self.env_vars if self.env_vars else None,
                timeout=self.timeout,
                output_callback=output_callback
            )

            if not result['success']:
                print(f"Command failed: {result.get('error', 'Unknown error')}")

            # Print execution summary
            if 'exit_info' in result and result['exit_info']:
                exit_info = result['exit_info']
                if exit_info['exit_code'] != 0:
                    print(f"Exit code: {exit_info['exit_code']}")

        except Exception as e:
            print(f"Command execution error: {e}")


class CommandPtyInteractiveSession(InteractiveSession):
    """Interactive command execution session (shell mode with PTY)"""

    async def run(self):
        """Run command PTY interactive mode"""
        print(f"Command PTY Interactive Mode (shell) - type 'help' for commands, 'quit' to exit")
        print("Full shell features enabled (pipes, &&, ||, etc) with real-time output")
        print()

        while True:
            try:
                try:
                    command = input(f"{self.service_name}-pty> ").strip()
                except EOFError:
                    # Support Ctrl+D
                    print()
                    break

                if not command:
                    continue

                if command in ["quit", "exit"]:
                    break

                elif command == "help":
                    self.show_help()

                elif await self.handle_special_command(command):
                    continue

                else:
                    # Execute through shell with PTY
                    await self._execute_command_shell(command)

            except KeyboardInterrupt:
                print("\nUse 'quit', 'exit', or Ctrl+D to exit")
            except Exception as e:
                print(f"Error: {e}")

    def show_help(self):
        """Show command PTY interactive help"""
        print("Command PTY mode: Shell features with real-time output")
        self.show_base_help()

    async def _execute_command_shell(self, command_str: str):
        """Execute shell command through bash with PTY"""
        try:
            # Check shell availability
            shell_cmd = 'cmd' if os.name == 'nt' else '/bin/bash'
            shell_name = shell_cmd.split('/')[-1]

            if not shutil.which(shell_name):
                print(f"Shell not available: {shell_name}")
                return

            # Use shell to execute the full command string with PTY
            if os.name == 'nt':
                argv = ['cmd', '/c', command_str]
            else:
                argv = ['/bin/bash', '-c', command_str]

            # Real-time output callback with color support
            def output_callback(stream_type: str, text: str):
                """Print output in real time with color coding"""
                if stream_type == 'stdout':
                    print(text, end='')
                elif stream_type == 'stderr':
                    # Print stderr in red
                    print(f'\033[31m{text}\033[0m', end='')
                sys.stdout.flush()

            result = await self.client.execute_command(
                command=argv,
                cwd=self.cwd,
                env=self.env_vars if self.env_vars else None,
                timeout=self.timeout,
                output_callback=output_callback,
                use_pty=True  # Force PTY for real-time output
            )

            if not result['success']:
                print(f"Command failed: {result.get('error', 'Unknown error')}")

            # Print execution summary
            if 'exit_info' in result and result['exit_info']:
                exit_info = result['exit_info']
                if exit_info['exit_code'] != 0:
                    print(f"Exit code: {exit_info['exit_code']}")

        except Exception as e:
            print(f"Command execution error: {e}")


async def quick_ping(service: str, address: str, message: str = "hello"):
    """Quick ping operation"""
    try:
        async with MeshWorkClient(service, address) as client:
            result = await client.ping(message)

            if result['success']:
                print(f"Ping successful: {result['message']}")
                print(f"Server time: {result['timestamp']}")
                return True
            else:
                print(f"Ping failed: {result['error']}")
                return False

    except Exception as e:
        print(f"Connection error: {e}")
        return False


async def quick_upload(service: str, address: str, file_path: str):
    """Quick upload operation"""
    if not Path(file_path).exists():
        print(f"File not found: {file_path}")
        return False

    try:
        async with MeshWorkClient(service, address) as client:
            progress = ProgressReporter(f"Uploading {file_path}")
            result = await client.upload_file(file_path, progress_callback=progress)

            if result['success']:
                print(f"Upload successful: {result['remote_path']}")
                print(f"Type: {type_to_string(result['type'])}")
                print(f"Bytes written: {format_bytes(result['bytes_written'])}")
                if result.get('files_extracted', 0) > 1:
                    print(f"Files extracted: {result['files_extracted']}")
                return True
            else:
                print(f"Upload failed: {result['error']}")
                return False

    except Exception as e:
        print(f"Upload error: {e}")
        return False


async def quick_download(service: str, address: str, file_path: str):
    """Quick download operation"""
    try:
        async with MeshWorkClient(service, address) as client:
            progress = ProgressReporter(f"Downloading {file_path}")
            result = await client.download_file(file_path, progress_callback=progress)

            if result['success']:
                print(f"Download successful: {result['local_path']}")
                print(f"Type: {type_to_string(result.get('type', 0))}")
                print(f"Bytes received: {format_bytes(result['bytes_written'])}")
                return True
            else:
                print(f"Download failed: {result['error']}")
                return False

    except Exception as e:
        print(f"Download error: {e}")
        return False


async def quick_delete(service: str, address: str, file_path: str):
    """Quick delete operation"""
    try:
        async with MeshWorkClient(service, address) as client:
            result = await client.delete_file(file_path)

            if result['success']:
                print(f"Delete successful: {result['remote_path']}")
                print(f"Type: {type_to_string(result['type'])}")
                if result.get('files_deleted', 0) > 1:
                    print(f"Files deleted: {result['files_deleted']}")
                else:
                    print("Files deleted: 1")
                return True
            else:
                print(f"Delete failed: {result['error']}")
                return False

    except Exception as e:
        print(f"Delete error: {e}")
        return False


async def interactive_python(service: str, address: str):
    """Interactive Python mode"""
    if service in ["colmap", "alicevision"]:
        print(f"Python execution not supported on {service} service")
        return False

    try:
        async with MeshWorkClient(service, address) as client:
            # Test connection first
            ping_result = await client.ping("python mode")
            if not ping_result['success']:
                print(f"Connection failed: {ping_result['error']}")
                return False

            print(f"Connected to {service} service")

            session = PythonInteractiveSession(client, service)
            await session.run()
            return True

    except Exception as e:
        print(f"Python mode error: {e}")
        return False


async def interactive_command(service: str, address: str):
    """Interactive command mode (argv)"""
    try:
        async with MeshWorkClient(service, address) as client:
            # Test connection first
            ping_result = await client.ping("command mode")
            if not ping_result['success']:
                print(f"Connection failed: {ping_result['error']}")
                return False

            session = CommandInteractiveSession(client, service)
            await session.run()
            return True

    except Exception as e:
        print(f"Command mode error: {e}")
        return False


async def interactive_command_pty(service: str, address: str):
    """Interactive command PTY mode (shell)"""
    try:
        async with MeshWorkClient(service, address) as client:
            # Test connection first
            ping_result = await client.ping("command PTY mode")
            if not ping_result['success']:
                print(f"Connection failed: {ping_result['error']}")
                return False

            session = CommandPtyInteractiveSession(client, service)
            await session.run()
            return True

    except Exception as e:
        print(f"Command PTY mode error: {e}")
        return False


def create_parser():
    """Create argument parser"""
    parser = argparse.ArgumentParser(
        description='MeshWork gRPC Client Test Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --ping
  %(prog)s --upload model.blend
  %(prog)s --upload ./assets/
  %(prog)s --download result.obj
  %(prog)s --download scene_output/
  %(prog)s --delete temp_file.txt
  %(prog)s --python
  %(prog)s --command
  %(prog)s --command-pty
        """
    )

    # Connection options
    parser.add_argument('--blender-addr', default='localhost',
                       help='Blender service address')
    parser.add_argument('--colmap-addr', default='localhost',
                       help='COLMAP service address')
    parser.add_argument('--alicevision-addr', default='localhost',
                       help='AliceVision service address')
    parser.add_argument('--service', choices=['blender', 'colmap', 'alicevision'],
                       default='blender', help='Target service')

    # Operation modes (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--ping', nargs='?', const='hello', metavar='MESSAGE',
                           help='Send ping request')
    mode_group.add_argument('--upload', metavar='PATH',
                           help='Upload file or directory')
    mode_group.add_argument('--download', metavar='PATH',
                           help='Download file or directory')
    mode_group.add_argument('--delete', metavar='PATH',
                           help='Delete file or directory')
    mode_group.add_argument('--python', action='store_true',
                           help='Interactive Python mode')
    mode_group.add_argument('--command', action='store_true',
                           help='Interactive command mode (argv, safe)')
    mode_group.add_argument('--command-pty', action='store_true',
                           help='Interactive command mode (shell, real-time)')

    return parser


async def main():
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    # Get service address
    service_addresses = {
        'blender': args.blender_addr,
        'colmap': args.colmap_addr,
        'alicevision': args.alicevision_addr
    }

    target_address = service_addresses[args.service]

    # Execute based on mode
    success = False

    try:
        if args.ping is not None:
            success = await quick_ping(args.service, target_address, args.ping)

        elif args.upload:
            success = await quick_upload(args.service, target_address, args.upload)

        elif args.download:
            success = await quick_download(args.service, target_address, args.download)

        elif args.delete:
            success = await quick_delete(args.service, target_address, args.delete)

        elif args.python:
            success = await interactive_python(args.service, target_address)

        elif args.command:
            success = await interactive_command(args.service, target_address)

        elif args.command_pty:
            success = await interactive_command_pty(args.service, target_address)

    except KeyboardInterrupt:
        print("\nOperation cancelled")
        success = False
    except Exception as e:
        print(f"Unexpected error: {e}")
        success = False

    # Proper async cleanup - wait a bit for resources to clean up
    try:
        await asyncio.sleep(0.1)
    except:
        pass

    return success


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(1)