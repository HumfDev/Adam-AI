"""MLP© 2025

Authors:
* Jamison Schmidt, jamison@mlp.global

==============================

Simple rotating file logger for MicroPython.

Provides basic logging methods and a rotating file handler to keep the log
bounded in size on constrained devices.
"""

import time
import os

# Log levels
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50

_level_names = {
    DEBUG: 'DEBUG',
    INFO: 'INFO', 
    WARNING: 'WARNING',
    ERROR: 'ERROR',
    CRITICAL: 'CRITICAL'
}

class RotatingFileHandler:
    """Append-only file writer with size-based rotation."""
    def __init__(self, filename, max_bytes=10240, backup_count=3):
        self.filename = filename
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.current_size = 0
        
        # Get current file size if it exists
        try:
            stat = os.stat(filename)
            self.current_size = stat[6]  # Size is at index 6
        except OSError:
            self.current_size = 0
    
    def _rotate(self):
        """Rotate log files when max size is reached"""
        try:
            # Remove oldest backup
            oldest = f"{self.filename}.{self.backup_count}"
            try:
                os.remove(oldest)
            except OSError:
                pass
            
            # Shift existing backups
            for i in range(self.backup_count, 0, -1):
                old_name = f"{self.filename}.{i-1}" if i > 1 else self.filename
                new_name = f"{self.filename}.{i}"
                try:
                    os.rename(old_name, new_name)
                except OSError:
                    pass
            
            self.current_size = 0
        except Exception:
            pass  # Fail silently on rotation errors
    
    def write(self, message):
        """Write message to log file with rotation check"""
        if self.current_size + len(message) > self.max_bytes:
            self._rotate()
        
        try:
            with open(self.filename, 'a') as f:
                f.write(message)
                self.current_size += len(message)
        except Exception:
            pass  # Fail silently on write errors

class Logger:
    """Minimal logger with level filtering and handler fanout."""
    def __init__(self, name="root", level=INFO):
        self.name = name
        self.level = level
        self.handlers = []
    
    def add_handler(self, handler):
        """Add a handler to this logger"""
        self.handlers.append(handler)
    
    def set_level(self, level):
        """Set the logging level"""
        self.level = level
    
    def _log(self, level, message):
        """Internal logging method"""
        if level < self.level:
            return
        
        # Format: YYYY-MM-DD HH:MM:SS LEVEL message
        try:
            t = time.localtime()
            timestamp = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
        except:
            timestamp = "----"
        
        level_name = _level_names.get(level, 'UNKNOWN')
        formatted = f"{timestamp} {level_name:8s} {message}\n"
        
        for handler in self.handlers:
            handler.write(formatted)
    
    def debug(self, message):
        self._log(DEBUG, message)
    
    def info(self, message):
        self._log(INFO, message)
    
    def warning(self, message):
        self._log(WARNING, message)
    
    def error(self, message):
        self._log(ERROR, message)
    
    def critical(self, message):
        self._log(CRITICAL, message)

# Global logger instance
_default_logger = None

def get_logger(name="root"):
    """Get a logger instance"""
    global _default_logger
    if _default_logger is None:
        _default_logger = Logger(name)
    return _default_logger

def get_log_entries(filename, n=0, level=None):
    """Read log entries from file with optional filtering
    
    Parameters
    ----------
    filename : str
        Path to log file
    n : int, default=0
        Number of lines to return (0 = all lines)
    level : str, optional
        Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns
    -------
    list[str] | dict
        List of log lines, or error dict on failure
    """
    try:
        # Read all lines
        try:
            with open(filename, 'r') as f:
                all_lines = [line.strip() for line in f.readlines()]
        except OSError:
            all_lines = []
        
        # TODO: Filter by level if specified
        if level is not None:
            level_upper = level.upper()
            all_lines = [line for line in all_lines if level_upper in line.split(' ')[2]]
        
        # Get last n lines if n > 0
        if n > 0:
            all_lines = all_lines[-n:]
        
        return all_lines
        
    except Exception as e:
        # TODO: Move this exception to main.py file
        return {'error': f"Error reading log file: {str(e)}"}

def clear_log_file(filename):
    """Clear log file by creating new empty file
    
    Parameters
    ----------
    filename : str
        Path to log file to clear
        
    Returns
    -------
    dict
        Result of clear operation
    """
    try:
        with open(filename, 'w') as f:
            pass  # Create empty file
        return {'info': f"Log file '{filename}' cleared successfully"}
    except Exception as e:
        return {'error': f"Error clearing log file: {str(e)}"}

def basic_config(filename="logs/log.txt", level=INFO, max_bytes=10240, backup_count=3):
    """Basic configuration for logging"""
    logger = get_logger()
    logger.set_level(level)
    
    if filename:
        handler = RotatingFileHandler(filename, max_bytes, backup_count)
        logger.add_handler(handler)
    
    return logger


# Setup logging
try:
    os.mkdir("logs")
except OSError:
    pass  # Directory already exists
