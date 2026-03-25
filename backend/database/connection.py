"""
Oracle ATP Database Connection Management
Handles database connections using oracledb with wallet authentication
"""
import oracledb
import logging
from contextlib import contextmanager
from typing import Optional, Generator
from config import config

# Set up logging
logging.basicConfig(level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Manages Oracle ATP database connections"""

    def __init__(self):
        """Initialize database connection parameters"""
        self.username = config.ATP_USERNAME
        self.password = config.ATP_PASSWORD
        self.dsn = config.ATP_SERVICE
        self.wallet_location = config.ATP_WALLET_DIR
        self.config_dir = config.ATP_CONFIG_DIR
        self._pool: Optional[oracledb.ConnectionPool] = None

    def initialize_pool(self, min_connections: int = 2, max_connections: int = 10):
        """
        Initialize connection pool for better performance

        Args:
            min_connections: Minimum number of connections in pool
            max_connections: Maximum number of connections in pool
        """
        try:
            # Initialize Oracle Client for Thick mode (required for wallet)
            oracledb.init_oracle_client(config_dir=self.config_dir)

            logger.info(f"Creating connection pool with DSN: {self.dsn}")
            self._pool = oracledb.create_pool(
                user=self.username,
                password=self.password,
                dsn=self.dsn,
                min=min_connections,
                max=max_connections,
                increment=1,
                getmode=oracledb.POOL_GETMODE_WAIT
            )
            logger.info("Database connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise

    @contextmanager
    def get_connection(self) -> Generator[oracledb.Connection, None, None]:
        """
        Context manager for database connections

        Yields:
            oracledb.Connection: Database connection object

        Example:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM pricing_cache")
        """
        conn = None
        try:
            if self._pool:
                conn = self._pool.acquire()
            else:
                # Fallback to direct connection if pool not initialized
                conn = oracledb.connect(
                    user=self.username,
                    password=self.password,
                    dsn=self.dsn,
                    config_dir=self.config_dir
                )

            yield conn

        except Exception as e:
            logger.error(f"Database connection error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    @contextmanager
    def get_cursor(self) -> Generator[oracledb.Cursor, None, None]:
        """
        Context manager that provides both connection and cursor

        Yields:
            oracledb.Cursor: Database cursor object

        Example:
            with db.get_cursor() as cursor:
                cursor.execute("SELECT * FROM pricing_cache")
                results = cursor.fetchall()
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database cursor error: {e}")
                raise
            finally:
                cursor.close()

    def execute_query(self, query: str, params: Optional[dict] = None) -> list:
        """
        Execute a SELECT query and return results

        Args:
            query: SQL SELECT query
            params: Optional query parameters

        Returns:
            list: Query results
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or {})
            return cursor.fetchall()

    def execute_dml(self, query: str, params: Optional[dict] = None) -> int:
        """
        Execute DML (INSERT, UPDATE, DELETE) and return rows affected

        Args:
            query: SQL DML query
            params: Optional query parameters

        Returns:
            int: Number of rows affected
        """
        with self.get_cursor() as cursor:
            cursor.execute(query, params or {})
            return cursor.rowcount

    def test_connection(self) -> bool:
        """
        Test database connectivity

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                result = cursor.fetchone()
                logger.info(f"Database connection test successful: {result}")
                return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False

    def close_pool(self):
        """Close the connection pool"""
        if self._pool:
            self._pool.close()
            logger.info("Database connection pool closed")


# Create global database instance
db = DatabaseConnection()
