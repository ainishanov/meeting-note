"""Logging configuration using loguru."""

import sys
import os
from pathlib import Path
from typing import Optional

from loguru import logger


def setup_logger(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
) -> None:
    """
    Configure application logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
    """
    try:
        # Remove default handler
        logger.remove()

        # Ensure log_level is a valid string
        if not log_level or not isinstance(log_level, str):
            log_level = "INFO"

        # File output format (no colors)
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        )

        # Add file handler first (this is the primary handler for GUI apps on Windows)
        if log_file is not None:
            try:
                # Get absolute path
                if isinstance(log_file, Path):
                    log_file_path = log_file.resolve()
                else:
                    log_file_path = Path(str(log_file)).resolve()

                # Create parent directory
                os.makedirs(log_file_path.parent, exist_ok=True)

                # Convert to string for loguru
                sink = str(log_file_path)

                logger.add(
                    sink,
                    format=file_format,
                    level=log_level,
                    rotation="10 MB",
                    retention="7 days",
                    compression="zip",
                    encoding="utf-8",
                )
            except Exception:
                pass  # File logging failed, continue

        # Try to add console handler
        try:
            stderr = sys.stderr
            if stderr is not None:
                console_format = (
                    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                    "<level>{level: <8}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                    "<level>{message}</level>"
                )
                logger.add(
                    stderr,
                    format=console_format,
                    level=log_level,
                    colorize=True,
                )
        except Exception:
            pass  # Console logging failed, continue

    except Exception:
        pass  # Complete failure, app will run without logging


def get_logger(name: str = __name__):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)
