import logging

import os
import sys

import traceback

from datetime import datetime


import colorama


RESET = "\033[0m"
COLORS = {
    logging.DEBUG: "\033[37m",  # gray
    logging.INFO: "\033[0m",  # white/default
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[41m",  # red background
}


class ColorFormatter(logging.Formatter):
    def format(self, record):
        log_color = COLORS.get(record.levelno, RESET)
        message = super().format(record)
        return f"{log_color}{message}{RESET}"


def setup_logger(level: str = logging.INFO):
    """
    Set up the logger with the specified log level.
    :param level: The logging level to set (e.g., logging.DEBUG, logging.INFO).
    """

    colorama.init()

    if level == "OFF":
        logging.disable(logging.CRITICAL)  # Disable all logs
    else:
        # Get the numeric log level from the string
        level = getattr(logging, level.upper(), logging.INFO)

        # Clear root logger handlers to avoid duplicate handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Create a new handler with color
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            ColorFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

        root_logger.setLevel(level)
        root_logger.addHandler(console_handler)
        
        # Telemetry Safety Net: Add a FileHandler for fatal crash logs
        # Ensure the logs directory exists
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # 1. Crash Log (Errors only)
        crash_log_path = os.path.join(log_dir, "crash.log")
        file_handler = logging.FileHandler(crash_log_path, encoding="utf-8")
        file_handler.setLevel(logging.ERROR) # Only log errors and critical crashes to file
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root_logger.addHandler(file_handler)

        # 2. Comprehensive JSON Telemetry Log (All levels)
        class ScrubbingJSONFormatter(logging.Formatter):
            import re
            # Basic patterns for scrubbing
            PII_PATTERNS = [
                (re.compile(r'\b(?:\d[ -]*?){13,16}\b'), '[SCRUBBED_CARD]'),
                (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[SCRUBBED_EMAIL]'),
                (re.compile(r'(?i)(api[_-]?key|secret|password)["\s:=]+([^\s,"]+)'), r'\1="[SCRUBBED]"')
            ]

            def format(self, record):
                import json
                msg = super().format(record)
                
                # Scrub PII
                for pattern, repl in self.PII_PATTERNS:
                    msg = pattern.sub(repl, msg)
                    
                log_record = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "level": record.levelname,
                    "name": record.name,
                    "message": msg,
                    "filename": record.filename,
                    "lineno": record.lineno,
                }
                if record.exc_info:
                    log_record["exc_info"] = self.formatException(record.exc_info)
                return json.dumps(log_record)

        telemetry_log_path = os.path.join(log_dir, "telemetry.jsonl")
        json_file_handler = logging.FileHandler(telemetry_log_path, encoding="utf-8")
        json_file_handler.setLevel(logging.DEBUG)  # Capture everything in telemetry
        json_file_handler.setFormatter(ScrubbingJSONFormatter())
        root_logger.addHandler(json_file_handler)

def global_exception_handler(exc_type, exc_value, exc_traceback):
    """
    Global exception handler to ensure unhandled exceptions are caught and logged with full stack traces.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
        
    logger = logging.getLogger("GlobalCrashHandler")
    logger.critical("Uncaught exception: %s", exc_value, exc_info=(exc_type, exc_value, exc_traceback))

# Install the global exception handler
sys.excepthook = global_exception_handler
