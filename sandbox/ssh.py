# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SSH session wrapper using paramiko."""

import re
import time

import paramiko


class SSHSession:
    """Thin wrapper around paramiko for SSH command execution.

    Maintains no persistent shell state — each run() is a fresh exec_command.
    This keeps the interface stateless and prevents agent confusion from cwd changes.
    """

    def __init__(
        self, host: str, port: int, user: str = "sre", password: str = "fix123"
    ):
        """Initialize SSH session.

        Args:
            host: Target hostname/IP
            port: SSH port
            user: Username (default: "sre")
            password: Password (default: "fix123")

        Raises:
            paramiko.AuthenticationException: If auth fails
            paramiko.SSHException: If connection fails
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client = None
        self._connect()

    def _connect(self):
        """Establish SSH connection."""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )

    def run(self, command: str, timeout: int = 10) -> tuple:
        """Execute a command and return output.

        Each run is a fresh exec_command — no persistent shell state.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds (default: 10)

        Returns:
            (stdout+stderr as str, exit_code as int)
        """
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command, timeout=timeout
            )
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            # Combine stdout and stderr
            output = out + err

            # Strip ANSI escape codes
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)

            return output, exit_code
        except Exception as e:
            # On error, return error message with non-zero exit code
            return str(e), 1

    def close(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
