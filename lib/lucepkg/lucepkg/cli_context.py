import dataclasses
import sys
from typing import Optional

import typer


@dataclasses.dataclass
class LuceContextObject:
    output_shell_commands_to: Optional[str] = None

    def enqueue_shell_command(self, command: str) -> None:
        """Add a shell command to be executed after the Python process exits.

        Args:
            command: Shell command to execute

        Raises:
            RuntimeError: If trying to enqueue a command outside the shell script context
        """
        if not self.output_shell_commands_to:
            print(
                "Error: This command produces shell commands that must be executed in your shell, "
                "but `luce` is not executing from a shell function. Did you run "
                "`source lib/lucepkg/scripts/activate_luce.sh` and then execute via `luce`?",
                file=sys.stderr,
            )
            raise typer.Exit(1)

        with open(self.output_shell_commands_to, "a") as f:
            f.write(f"{command}\n")
