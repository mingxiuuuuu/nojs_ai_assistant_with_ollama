import sqlite3
import aiosqlite
import logging
import time
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager
from pathlib import Path
from config import config
from utils.timezone_utils import now_local, format_local_datetime, parse_local_datetime, utc_to_local
from utils.logging_config import log_performance

logger = logging.getLogger(__name__)

class DatabaseService:
    """Async database service for chat messages"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_URL.replace("sqlite:///", "")
        self._initialized = False

    async def initialize(self):
        """Initialize database with required tables"""
        if self._initialized:
            return

        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Create chat_sessions table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL DEFAULT 'New Chat',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        message_count INTEGER DEFAULT 0,
                        is_active BOOLEAN DEFAULT 1
                    )
                """)

                # Create messages table with session_id
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        model TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        response_time REAL,
                        token_count INTEGER,
                        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
                    )
                """)

                # Create indexes for better performance
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON chat_sessions(updated_at)"
                )

                # Migrate existing messages to default session if needed
                await self._migrate_existing_messages(db)

                await db.commit()
                logger.info(f"Database initialized at {self.db_path}")
                self._initialized = True

        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

    @asynccontextmanager
    async def get_connection(self):
        """Get async database connection"""
        if not self._initialized:
            await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            yield db

    async def _migrate_existing_messages(self, db):
        """Migrate existing messages to default session"""
        try:
            # Check if there are messages without session_id
            cursor = await db.execute("SELECT COUNT(*) as count FROM messages WHERE session_id IS NULL")
            result = await cursor.fetchone()

            if result and result['count'] > 0:
                # Create default session with local timezone
                local_now = format_local_datetime(now_local(), "%Y-%m-%d %H:%M:%S")
                cursor = await db.execute(
                    "INSERT INTO chat_sessions (title, created_at, updated_at, message_count) VALUES (?, ?, ?, ?)",
                    ("Imported Chat", local_now, local_now, result['count'])
                )
                session_id = cursor.lastrowid

                # Update messages to belong to default session
                await db.execute(
                    "UPDATE messages SET session_id = ? WHERE session_id IS NULL",
                    (session_id,)
                )
                logger.info(f"Migrated {result['count']} existing messages to session {session_id}")
        except Exception as e:
            logger.warning(f"Migration warning: {str(e)}")

    async def save_message(self, role: str, content: str, session_id: int = None, model: str = None,
                          response_time: float = None, token_count: int = None) -> int:
        """Save a message to the database"""
        start_time = time.time()
        
        try:
            # If no session_id provided, create a new session
            if session_id is None:
                session_id = await self.create_session()

            async with self.get_connection() as db:
                # Use local timezone for created_at
                local_now = format_local_datetime(now_local(), "%Y-%m-%d %H:%M:%S")
                cursor = await db.execute(
                    """
                    INSERT INTO messages (session_id, role, content, model, created_at, response_time, token_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, model, local_now, response_time, token_count)
                )
                await db.commit()
                message_id = cursor.lastrowid

                # Update session message count and updated_at with local timezone
                await db.execute(
                    "UPDATE chat_sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
                    (local_now, session_id)
                )
                await db.commit()

                # Log performance if operation takes too long
                duration = time.time() - start_time
                if duration > config.PERFORMANCE_LOG_THRESHOLD:
                    log_performance(
                        operation="db_save_message",
                        duration=duration,
                        session_id=session_id,
                        role=role,
                        content_length=len(content)
                    )

                logger.debug(f"Saved message {message_id}: {role} in session {session_id}")
                return message_id

        except Exception as e:
            logger.error(f"Failed to save message: {str(e)}")
            raise

    async def get_recent_messages(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from the database"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT role, content, model, created_at, response_time
                    FROM messages
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get recent messages: {str(e)}")
            return []

    async def create_session(self, title: str = "New Chat") -> int:
        """Create a new chat session"""
        start_time = time.time()
        
        try:
            async with self.get_connection() as db:
                local_now = format_local_datetime(now_local(), "%Y-%m-%d %H:%M:%S")
                cursor = await db.execute(
                    "INSERT INTO chat_sessions (title, created_at, updated_at, message_count) VALUES (?, ?, ?, 0)",
                    (title, local_now, local_now)
                )
                await db.commit()
                session_id = cursor.lastrowid
                
                # Log performance if operation takes too long
                duration = time.time() - start_time
                if duration > config.PERFORMANCE_LOG_THRESHOLD:
                    log_performance(
                        operation="db_create_session",
                        duration=duration,
                        title=title
                    )
                
                logger.debug(f"Created new session {session_id}: {title} with message_count=0")
                return session_id
        except Exception as e:
            logger.error(f"Failed to create session: {str(e)}")
            raise

    async def get_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all chat sessions ordered by most recent"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT id, title, created_at, updated_at, message_count, is_active
                    FROM chat_sessions
                    WHERE is_active = 1
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get sessions: {str(e)}")
            return []

    async def get_session(self, session_id: int) -> Dict[str, Any]:
        """Get a specific session by ID"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    "SELECT id, title, created_at, updated_at, message_count, is_active FROM chat_sessions WHERE id = ?",
                    (session_id,)
                )
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {str(e)}")
            return None

    async def update_session_title(self, session_id: int, title: str) -> bool:
        """Update session title"""
        logger.debug(f"DEBUG: update_session_title called for session {session_id} with title: '{title}'")
        try:
            async with self.get_connection() as db:
                local_now = format_local_datetime(now_local(), "%Y-%m-%d %H:%M:%S")
                cursor = await db.execute(
                    "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (title, local_now, session_id)
                )
                await db.commit()
                rows_affected = cursor.rowcount
                logger.debug(f"DEBUG: Title update for session {session_id} affected {rows_affected} rows")

                if rows_affected > 0:
                    logger.info(f"DEBUG: Successfully updated title for session {session_id} to: '{title}'")
                    return True
                else:
                    logger.warning(f"DEBUG: No rows affected when updating title for session {session_id}")
                    return False
        except Exception as e:
            logger.error(f"Failed to update session title: {str(e)}")
            return False

    async def delete_session(self, session_id: int) -> bool:
        """Delete a session and all its messages"""
        try:
            async with self.get_connection() as db:
                await db.execute("UPDATE chat_sessions SET is_active = 0 WHERE id = ?", (session_id,))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete session: {str(e)}")
            return False

    async def get_conversation_history(self, session_id: int = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get conversation history from the database for a specific session"""
        start_time = time.time()
        
        try:
            async with self.get_connection() as db:
                if session_id:
                    cursor = await db.execute(
                        """
                        SELECT role, content, model, created_at, response_time, token_count
                        FROM messages
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (session_id, limit)
                    )
                else:
                    # Get latest session if no session_id provided
                    session_cursor = await db.execute(
                        "SELECT id FROM chat_sessions WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
                    )
                    session_result = await session_cursor.fetchone()
                    if not session_result:
                        return []

                    cursor = await db.execute(
                        """
                        SELECT role, content, model, created_at, response_time, token_count
                        FROM messages
                        WHERE session_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (session_result['id'], limit)
                    )

                messages = await cursor.fetchall()
                
                # Log performance if operation takes too long
                duration = time.time() - start_time
                if duration > config.PERFORMANCE_LOG_THRESHOLD:
                    log_performance(
                        operation="db_get_conversation_history",
                        duration=duration,
                        session_id=session_id,
                        message_count=len(messages),
                        limit=limit
                    )
                
                # Convert timestamps to local timezone and reverse to get chronological order
                result = []
                for row in reversed(messages):
                    message_dict = dict(row)
                    if message_dict.get('created_at'):
                        # The timestamp is already in local timezone, just format it for display
                        message_dict['created_at'] = message_dict['created_at']
                    result.append(message_dict)
                return result

        except Exception as e:
            logger.error(f"Failed to get conversation history: {str(e)}")
            return []

    async def get_conversation_context(self, session_id: int, max_tokens: int = 3000) -> List[Dict[str, str]]:
        """Get recent messages that fit within token limit for context"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    """
                    SELECT role, content, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    (session_id,)
                )

                messages = await cursor.fetchall()
                context = []
                token_count = 0

                # Process messages in reverse order (oldest first for context)
                for row in reversed(messages):
                    role, content, timestamp = row['role'], row['content'], row['created_at']
                    # Rough token estimation: ~1.3 tokens per word
                    estimated_tokens = len(content.split()) * 1.3

                    if token_count + estimated_tokens < max_tokens:
                        context.append({"role": role, "content": content})
                        token_count += estimated_tokens
                    else:
                        break

                logger.debug(f"Retrieved {len(context)} messages for context (estimated {token_count:.0f} tokens)")
                return context

        except Exception as e:
            logger.error(f"Failed to get conversation context: {str(e)}")
            return []

    async def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            async with self.get_connection() as db:
                # Total messages
                cursor = await db.execute("SELECT COUNT(*) as total FROM messages")
                total_row = await cursor.fetchone()
                total_messages = total_row['total'] if total_row else 0

                # Messages by role
                cursor = await db.execute(
                    "SELECT role, COUNT(*) as count FROM messages GROUP BY role"
                )
                role_counts = {row['role']: row['count'] for row in await cursor.fetchall()}

                # Average response time
                cursor = await db.execute(
                    "SELECT AVG(response_time) as avg_time FROM messages WHERE response_time IS NOT NULL"
                )
                avg_time_row = await cursor.fetchone()
                avg_response_time = avg_time_row['avg_time'] if avg_time_row else 0

                return {
                    'total_messages': total_messages,
                    'role_counts': role_counts,
                    'average_response_time': avg_response_time
                }

        except Exception as e:
            logger.error(f"Failed to get statistics: {str(e)}")
            return {}

    async def cleanup_old_messages(self, days: int = 30) -> int:
        """Clean up messages older than specified days"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    """
                    DELETE FROM messages
                    WHERE created_at < datetime('now', '-{} days')
                    """.format(days)
                )
                await db.commit()
                deleted_count = cursor.rowcount
                logger.info(f"Cleaned up {deleted_count} old messages")
                return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup old messages: {str(e)}")
            return 0

    async def health_check(self) -> bool:
        """Check database health"""
        try:
            async with self.get_connection() as db:
                await db.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return False

    async def close(self):
        """Close the database service and cleanup resources"""
        # Since we're using aiosqlite with context managers,
        # there's no persistent connection to close
        # This method exists for consistency with the service interface
        self._initialized = False
        logger.info("Database service closed")

    async def update_last_assistant_message(self, session_id: int, new_content: str):
        """Update the last assistant message in a session"""
        try:
            async with self.get_connection() as db:
                cursor = await db.execute(
                    """
                    UPDATE messages
                    SET content = ?, created_at = datetime('now')
                    WHERE session_id = ? AND role = 'assistant'
                    AND id = (
                        SELECT id FROM messages 
                        WHERE session_id = ? AND role = 'assistant' 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    )
                    """,
                    (new_content, session_id, session_id)
                )
                await db.commit()
                rows_affected = cursor.rowcount
                logger.debug(f"Updated last assistant message for session {session_id}, rows affected: {rows_affected}")
                return rows_affected > 0
        except Exception as e:
            logger.error(f"Error updating last assistant message: {e}")
            raise

# Global database service instance
db_service = DatabaseService()