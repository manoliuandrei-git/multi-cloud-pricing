"""
Database Initialization Script
Creates all tables, indexes, views, and procedures defined in schema.sql
"""
import sys
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from database.connection import db
from config import config

# Set up logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def read_sql_file(file_path: str) -> list:
    """
    Read SQL file and split into individual statements

    Args:
        file_path: Path to SQL file

    Returns:
        list: List of SQL statements
    """
    with open(file_path, 'r') as f:
        content = f.read()

    # Split by semicolon but handle PL/SQL blocks
    statements = []
    current_statement = []
    in_plsql_block = False

    for line in content.split('\n'):
        # Skip comments
        if line.strip().startswith('--') or not line.strip():
            continue

        # Check for PL/SQL block start
        if any(keyword in line.upper() for keyword in ['CREATE OR REPLACE PROCEDURE', 'CREATE OR REPLACE FUNCTION', 'BEGIN']):
            in_plsql_block = True

        current_statement.append(line)

        # Check for statement end
        if line.strip().endswith(';'):
            if not in_plsql_block or line.strip() == '/':
                statement = '\n'.join(current_statement)
                if statement.strip() and not statement.strip().startswith('--'):
                    statements.append(statement)
                current_statement = []
                in_plsql_block = False

    return statements


def execute_sql_statements(statements: list) -> tuple:
    """
    Execute list of SQL statements

    Args:
        statements: List of SQL statements

    Returns:
        tuple: (success_count, failure_count, errors)
    """
    success_count = 0
    failure_count = 0
    errors = []

    with db.get_connection() as conn:
        cursor = conn.cursor()

        for i, statement in enumerate(statements, 1):
            try:
                logger.info(f"Executing statement {i}/{len(statements)}")
                logger.debug(f"SQL: {statement[:100]}...")

                cursor.execute(statement)
                conn.commit()
                success_count += 1
                logger.info(f"✓ Statement {i} executed successfully")

            except Exception as e:
                failure_count += 1
                error_msg = f"✗ Statement {i} failed: {str(e)}"
                logger.error(error_msg)
                errors.append((i, statement[:100], str(e)))

                # Continue with next statement
                try:
                    conn.rollback()
                except:
                    pass

        cursor.close()

    return success_count, failure_count, errors


def check_tables_exist() -> dict:
    """
    Check which tables already exist in the database

    Returns:
        dict: Dictionary of table names and their existence status
    """
    tables_to_check = [
        'pricing_cache',
        'pricing_cache_history',
        'service_mappings',
        'oci_pricing_docs',
        'doc_chunks',
        'log_agents',
        'user_selections'
    ]

    results = {}

    try:
        with db.get_cursor() as cursor:
            for table in tables_to_check:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM user_tables
                    WHERE UPPER(table_name) = UPPER(:table_name)
                """, {'table_name': table})

                count = cursor.fetchone()[0]
                results[table] = count > 0

    except Exception as e:
        logger.error(f"Error checking tables: {e}")

    return results


def drop_all_tables():
    """Drop all application tables (use with caution!)"""
    tables = [
        'user_selections',
        'doc_chunks',
        'log_agents',
        'oci_pricing_docs',
        'pricing_cache_history',
        'service_mappings',
        'pricing_cache'
    ]

    logger.warning("Dropping all tables...")

    with db.get_connection() as conn:
        cursor = conn.cursor()

        for table in tables:
            try:
                cursor.execute(f"DROP TABLE {table} CASCADE CONSTRAINTS")
                conn.commit()
                logger.info(f"✓ Dropped table: {table}")
            except Exception as e:
                logger.warning(f"Could not drop table {table}: {e}")

        cursor.close()


def main():
    """Main initialization function"""
    logger.info("=" * 60)
    logger.info("Multi-Cloud Pricing Calculator - Database Initialization")
    logger.info("=" * 60)

    # Test database connection
    logger.info("\n1. Testing database connection...")
    if not db.test_connection():
        logger.error("Database connection failed. Please check your configuration.")
        return False

    logger.info("✓ Database connection successful")

    # Check existing tables
    logger.info("\n2. Checking existing tables...")
    existing_tables = check_tables_exist()

    for table, exists in existing_tables.items():
        status = "EXISTS" if exists else "NOT FOUND"
        logger.info(f"  - {table}: {status}")

    # Ask user if they want to proceed
    if any(existing_tables.values()):
        logger.warning("\nSome tables already exist!")
        response = input("Do you want to drop existing tables and recreate? (yes/no): ")

        if response.lower() == 'yes':
            drop_all_tables()
        else:
            logger.info("Skipping table creation. Exiting.")
            return False

    # Read schema file
    logger.info("\n3. Reading schema file...")
    schema_file = Path(__file__).parent / 'schema.sql'

    if not schema_file.exists():
        logger.error(f"Schema file not found: {schema_file}")
        return False

    statements = read_sql_file(str(schema_file))
    logger.info(f"✓ Found {len(statements)} SQL statements")

    # Execute statements
    logger.info("\n4. Executing SQL statements...")
    success_count, failure_count, errors = execute_sql_statements(statements)

    # Report results
    logger.info("\n" + "=" * 60)
    logger.info("INITIALIZATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {failure_count}")

    if errors:
        logger.warning("\nErrors encountered:")
        for stmt_num, sql_preview, error in errors:
            logger.warning(f"Statement {stmt_num}: {error}")

    # Verify tables
    logger.info("\n5. Verifying table creation...")
    final_tables = check_tables_exist()

    for table, exists in final_tables.items():
        status = "✓" if exists else "✗"
        logger.info(f"  {status} {table}")

    all_created = all(final_tables.values())

    if all_created:
        logger.info("\n✓ All tables created successfully!")
        return True
    else:
        logger.error("\n✗ Some tables failed to create. Check errors above.")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nInitialization cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
