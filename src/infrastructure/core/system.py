"""
System-level utilities for infrastructure layer.
Contains platform detection, resource management, and system configuration helpers.
"""
import asyncio
import logging
import os
from typing import Any, Coroutine, Optional, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in a fresh event loop, draining pending tasks before
    closing the loop.

    Drop-in replacement for ``asyncio.run()`` in Celery prefork workers.
    ``asyncio.run()`` closes the loop immediately after the main coroutine
    returns, which causes LangChain/httpx background cleanup tasks to log
    ``RuntimeError('Event loop is closed')`` at ERROR level.  Running
    ``asyncio.gather`` on all remaining tasks first lets httpx close its
    connections cleanly before the loop is shut down.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        loop.close()

log = logging.getLogger(__name__)


def get_max_workers(config_max_workers: Optional[int] = None) -> int:
    """
    Determine the maximum number of workers for parallel processing.
    
    This function is Lambda-aware and provides intelligent defaults based on
    the execution environment. It follows a priority order:
    1. Explicit config value (if provided)
    2. MAX_WORKERS environment variable
    3. Auto-detection based on CPU count (Lambda-aware)
    
    For Lambda environments:
    - Lambda has limited CPU resources (1 vCPU per ~1.769 GB memory)
    - Conservative defaults: 2-4 workers max
    - Use environment variable MAX_WORKERS to override
    
    Args:
        config_max_workers: Optional max workers from config
        
    Returns:
        Maximum number of workers to use (always >= 1)
    """
    # 1. Check explicit config value
    if config_max_workers is not None:
        return max(1, config_max_workers)  # Ensure at least 1
    
    # 2. Check environment variable
    env_max_workers = os.getenv("MAX_WORKERS")
    if env_max_workers:
        try:
            workers = int(env_max_workers)
            return max(1, workers)
        except ValueError:
            log.warning(f"Invalid MAX_WORKERS env var value: {env_max_workers}, using auto-detection")
    
    # 3. Auto-detection (Lambda-aware)
    try:
        cpu_count = os.cpu_count() or 1
        # For Lambda: be conservative (typically 1-2 vCPUs)
        # For other environments: use CPU count but cap at reasonable limit
        # Lambda detection: check if running in Lambda environment
        is_lambda = os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None
        
        if is_lambda:
            # Lambda: conservative approach
            # Typically 1-2 vCPUs, so use 2-4 workers max
            max_workers = min(cpu_count * 2, 4)
        else:
            # Non-Lambda: use CPU count but cap at 10 for safety
            max_workers = min(cpu_count, 10)
        
        return max(1, max_workers)  # Ensure at least 1
    except Exception as e:
        log.warning(f"Error detecting CPU count: {e}, defaulting to 2 workers")
        return 2


