"""
Pricing Refresh Utility
Handles daily pricing updates from all cloud providers
"""
import time
from datetime import datetime, timedelta
from typing import Dict
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from database.queries import (
    archive_pricing_to_history,
    bulk_insert_pricing_data,
    delete_old_pricing,
    check_pricing_freshness
)
from api_integrations.aws_pricing import fetch_aws_pricing
from api_integrations.azure_pricing import fetch_azure_pricing
from api_integrations.gcp_pricing import fetch_gcp_pricing
from api_integrations.oci_storage import fetch_oci_documents, OCIStorageClient
from utils.logger import get_logger

logger = get_logger(__name__)


class PricingRefreshManager:
    """Manages pricing data refresh from all cloud providers"""

    def __init__(self):
        """Initialize pricing refresh manager"""
        self.scheduler = BackgroundScheduler()

    def check_if_refresh_needed(self) -> bool:
        """
        Check if pricing data needs refresh.

        Returns True if:
        - No pricing data at all
        - Any provider's data is older than 1 day
        - OCI is missing from the cache (RAG-based, should always be present)

        Returns:
            bool: True if refresh needed
        """
        try:
            freshness = check_pricing_freshness()

            if not freshness:
                logger.info("No pricing data found, refresh needed")
                return True

            # OCI uses local PDF extraction — always refresh if missing
            if 'OCI' not in freshness:
                logger.info("OCI pricing missing from cache, refresh needed")
                return True

            # Check if any provider's data is older than 1 day
            for provider, last_updated in freshness.items():
                if last_updated:
                    age = datetime.now() - last_updated
                    if age > timedelta(days=1):
                        logger.info(f"{provider} pricing is {age.days} days old, refresh needed")
                        return True

            logger.info("Pricing data is fresh, no refresh needed")
            return False

        except Exception as e:
            logger.error(f"Failed to check pricing freshness: {e}")
            return True  # Refresh on error to be safe

    def refresh_all_pricing(self, force: bool = False) -> Dict:
        """
        Refresh pricing data from all cloud providers

        Args:
            force: If True, refresh even if data is fresh

        Returns:
            Dict with refresh statistics
        """
        start_time = time.time()

        stats = {
            'started_at': datetime.now().isoformat(),
            'providers': {},
            'total_records': 0,
            'duration_seconds': 0,
            'success': False
        }

        try:
            # OCI is PDF-based (local extraction, no external API calls) so always run it
            # regardless of the freshness check — it's fast and free
            logger.info("Running OCI pricing refresh (local PDF extraction)")
            stats['providers']['oci'] = self._refresh_oci_pricing()

            # For the remaining providers (external APIs), respect the freshness check
            if not force and not self.check_if_refresh_needed():
                logger.info("API-based pricing data is fresh, skipping AWS/Azure/GCP refresh")
                stats['total_records'] = stats['providers']['oci'].get('records_inserted', 0)
                stats['duration_seconds'] = round(time.time() - start_time, 2)
                stats['success'] = True
                return stats

            logger.info("Starting pricing refresh for all cloud providers")

            # Step 1: Archive current pricing to history
            logger.info("Archiving current pricing to history")
            archived_count = archive_pricing_to_history()
            logger.info(f"Archived {archived_count} pricing records")

            # Step 2: Fetch AWS pricing
            stats['providers']['aws'] = self._refresh_provider_pricing(
                provider='AWS',
                fetch_function=fetch_aws_pricing,
                categories=['Database', 'Compute', 'Storage']
            )

            # Step 3: Fetch Azure pricing
            stats['providers']['azure'] = self._refresh_provider_pricing(
                provider='Azure',
                fetch_function=fetch_azure_pricing,
                categories=['Database', 'Compute', 'Storage']
            )

            # Step 4: Fetch GCP pricing (if enabled)
            stats['providers']['gcp'] = self._refresh_provider_pricing(
                provider='GCP',
                fetch_function=fetch_gcp_pricing,
                categories=['Database', 'Compute', 'Storage']
            )

            # OCI was already run above (before the freshness check) — skip here

            # Calculate totals
            stats['total_records'] = sum(
                p.get('records_inserted', 0)
                for p in stats['providers'].values()
            )

            stats['duration_seconds'] = round(time.time() - start_time, 2)
            stats['success'] = True

            logger.info(f"Pricing refresh completed: {stats['total_records']} records in {stats['duration_seconds']}s")

        except Exception as e:
            logger.error(f"Pricing refresh failed: {e}", exc_info=True)
            stats['error'] = str(e)
            stats['success'] = False

        finally:
            stats['completed_at'] = datetime.now().isoformat()

        return stats

    def _refresh_provider_pricing(
        self,
        provider: str,
        fetch_function,
        categories: list
    ) -> Dict:
        """
        Refresh pricing for a specific cloud provider

        Args:
            provider: Provider name (AWS, Azure, GCP)
            fetch_function: Function to fetch pricing data
            categories: List of service categories

        Returns:
            Dict with provider refresh stats
        """
        provider_stats = {
            'records_fetched': 0,
            'records_inserted': 0,
            'errors': []
        }

        try:
            logger.info(f"Fetching {provider} pricing data")

            # Fetch pricing data
            pricing_data = fetch_function()
            provider_stats['records_fetched'] = len(pricing_data)

            if not pricing_data:
                logger.warning(f"No pricing data fetched for {provider}")
                return provider_stats

            # Delete old pricing for this provider
            for category in categories:
                deleted = delete_old_pricing(provider, category)
                logger.info(f"Deleted {deleted} old {provider} {category} records")

            # Insert new pricing data
            if pricing_data:
                inserted = bulk_insert_pricing_data(pricing_data)
                provider_stats['records_inserted'] = inserted
                logger.info(f"Inserted {inserted} {provider} pricing records")

        except Exception as e:
            error_msg = f"Failed to refresh {provider} pricing: {str(e)}"
            logger.error(error_msg)
            provider_stats['errors'].append(error_msg)

        return provider_stats

    def _refresh_oci_pricing(self) -> Dict:
        """
        Refresh OCI pricing via local PDF extraction.

        Downloads the Oracle Global Price List PDF from OCI Object Storage,
        parses it locally with pdfplumber (no API calls, no RAG), and inserts
        all pricing rows into pricing_cache.

        Returns:
            Dict with OCI refresh stats
        """
        oci_stats = {
            'documents_processed': 0,
            'records_fetched': 0,
            'records_inserted': 0,
            'errors': []
        }

        try:
            logger.info("Refreshing OCI pricing (local PDF extraction)...")

            # Ensure the PDF is present in OCI Object Storage
            doc_stats = fetch_oci_documents(force_refresh=False)
            oci_stats['documents_processed'] = doc_stats.get('documents_processed', 0)
            if doc_stats.get('errors'):
                oci_stats['errors'].extend(doc_stats['errors'])

            # Download and parse each PDF directly
            all_oci_pricing = []
            storage_client = OCIStorageClient()
            object_names = storage_client.list_documents(file_extension='.pdf')

            if not object_names:
                logger.warning("No PDFs found in OCI bucket — skipping OCI pricing refresh")
                return oci_stats

            for obj_name in object_names:
                logger.info(f"Extracting pricing from '{obj_name}'...")
                pricing_rows = storage_client.extract_all_pricing_direct(
                    obj_name, region='eu-zurich-1'
                )
                logger.info(f"  → {len(pricing_rows)} rows extracted from '{obj_name}'")
                all_oci_pricing.extend(pricing_rows)

            oci_stats['records_fetched'] = len(all_oci_pricing)

            if not all_oci_pricing:
                logger.warning("PDF extraction returned no rows — OCI pricing not updated")
                return oci_stats

            # Delete old OCI data and insert fresh rows
            categories_to_purge = set(
                r.get('service_category', 'Unknown') for r in all_oci_pricing
            )
            for category in categories_to_purge:
                deleted = delete_old_pricing('OCI', category)
                if deleted:
                    logger.info(f"Deleted {deleted} old OCI/{category} records")

            inserted = bulk_insert_pricing_data(all_oci_pricing)
            oci_stats['records_inserted'] = inserted
            logger.info(f"OCI pricing refresh complete: {inserted} records inserted")

        except Exception as e:
            error_msg = f"Failed to refresh OCI pricing: {e}"
            logger.error(error_msg, exc_info=True)
            oci_stats['errors'].append(error_msg)

        return oci_stats

    def schedule_daily_refresh(self):
        """Schedule daily pricing refresh at configured time"""
        # Parse refresh time (format: HH:MM)
        hour, minute = map(int, config.PRICING_REFRESH_TIME.split(':'))

        # Create cron trigger
        trigger = CronTrigger(hour=hour, minute=minute)

        # Add job to scheduler
        self.scheduler.add_job(
            func=self.refresh_all_pricing,
            trigger=trigger,
            id='daily_pricing_refresh',
            name='Daily Pricing Refresh',
            replace_existing=True
        )

        logger.info(f"Scheduled daily pricing refresh at {config.PRICING_REFRESH_TIME}")

    def start_scheduler(self):
        """Start the background scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Pricing refresh scheduler started")

    def stop_scheduler(self):
        """Stop the background scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Pricing refresh scheduler stopped")


# Global instance
pricing_manager = PricingRefreshManager()


# Convenience functions
def refresh_pricing_now(force: bool = False) -> Dict:
    """
    Refresh pricing data immediately

    Args:
        force: Force refresh even if data is fresh

    Returns:
        Dict with refresh statistics
    """
    return pricing_manager.refresh_all_pricing(force=force)


def start_scheduled_refresh():
    """Start the scheduled daily pricing refresh"""
    pricing_manager.schedule_daily_refresh()
    pricing_manager.start_scheduler()


def stop_scheduled_refresh():
    """Stop the scheduled daily pricing refresh"""
    pricing_manager.stop_scheduler()
