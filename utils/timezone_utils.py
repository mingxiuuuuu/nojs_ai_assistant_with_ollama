"""Timezone utilities for the AI Assistant application.

This module provides timezone-aware datetime functions to ensure consistent
timestamp handling across the application using the configured timezone.
"""

from datetime import datetime
from typing import Optional
import pytz
from config import config


def get_timezone():
    """Get the configured timezone object."""
    return pytz.timezone(config.TIMEZONE)


def now_local() -> datetime:
    """Get current datetime in the configured timezone."""
    tz = get_timezone()
    return datetime.now(tz)


def utc_to_local(utc_dt: datetime) -> datetime:
    """Convert UTC datetime to local timezone."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
    elif utc_dt.tzinfo != pytz.UTC:
        utc_dt = utc_dt.astimezone(pytz.UTC)
    
    tz = get_timezone()
    return utc_dt.astimezone(tz)


def local_to_utc(local_dt: datetime) -> datetime:
    """Convert local timezone datetime to UTC."""
    tz = get_timezone()
    if local_dt.tzinfo is None:
        local_dt = tz.localize(local_dt)
    
    return local_dt.astimezone(pytz.UTC)


def format_local_datetime(dt: Optional[datetime] = None, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime in local timezone."""
    if dt is None:
        dt = now_local()
    elif dt.tzinfo is None or dt.tzinfo != get_timezone():
        dt = utc_to_local(dt)
    
    return dt.strftime(format_str)


def parse_local_datetime(dt_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """Parse datetime string as local timezone."""
    dt = datetime.strptime(dt_str, format_str)
    tz = get_timezone()
    return tz.localize(dt)


def get_local_timestamp() -> float:
    """Get current timestamp adjusted for local timezone."""
    return now_local().timestamp()


def timestamp_to_local(timestamp: float) -> datetime:
    """Convert timestamp to local timezone datetime."""
    utc_dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
    return utc_to_local(utc_dt)