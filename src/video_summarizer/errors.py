"""Shared exception types.

ConfigError  -> usage/config problem before any work was done; CLI maps to exit 2.
StageError   -> a single pipeline stage failed; isolated so other stages still run; CLI maps to exit 1.
"""


class ConfigError(Exception):
    """Missing required tool, env var, or invalid arguments."""


class StageError(Exception):
    """A pipeline stage failed but the run can continue with partial output."""
