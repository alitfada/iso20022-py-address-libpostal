import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


class AppLogger:
    _instance = None
    _initialized = False


    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


    def __init__(self):
        if not self._initialized:
            self.logger = logging.getLogger('structured_address')
            self.logger.setLevel(logging.DEBUG)
            self._initialized = True


    def configure(self, log_dir: Path):
        """Configure file logging to specified directory"""
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / 'application.log'

            # Clear existing handlers to avoid duplicates
            self.logger.handlers.clear()

            # File handler (rotating logs)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=15*1024*1024,  # 15MB
                backupCount=10,
                encoding='utf-8'
            )
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            self.logger.addHandler(file_handler)

            # Console handler
            #console_handler = logging.StreamHandler()
            #console_handler.setLevel(logging.INFO)
            #self.logger.addHandler(console_handler)

            self.logger.info("Logging configured to %s", log_file)
            return True

        except Exception as e:
            self.logger.error("Failed to configure file logging: %s", str(e))
            return False


def get_logger():
    """Get the application logger instance"""
    return AppLogger().logger
