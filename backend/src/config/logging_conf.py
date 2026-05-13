import logging
from logging.config import dictConfig

# Стандартная конфигурация логов для проекта
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        },
        "uvicorn": {
            "format": "%(levelprefix)s %(message)s",
            "use_colors": True,
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
        "uvicorn_console": {
            "class": "logging.StreamHandler",
            "formatter": "uvicorn",
        },
    },

    "loggers": {
        "": {
            "level": "INFO",
            "handlers": ["console"],
        },
        "uvicorn": {
            "level": "INFO",
            "handlers": ["uvicorn_console"],
            "propagate": False,
        },
        "uvicorn.error": {
            "level": "INFO",
            "handlers": ["uvicorn_console"],
            "propagate": False,
        },
        "uvicorn.access": {
            "level": "INFO",
            "handlers": ["uvicorn_console"],
            "propagate": False,
        },
    },
}


def setup_logging():
    # Dlya sebya: konfiguracionnyy helper (setup logging).
    dictConfig(LOGGING_CONFIG)
