"""
GCP Cloud Billing Catalog API Integration
Fetches pricing data from Google Cloud Platform

Note: Temporarily disabled - requires GCP service account credentials
"""
from typing import List, Dict
from utils.logger import get_logger

logger = get_logger(__name__)


class GCPPricingClient:
    """Client for GCP Cloud Billing Catalog API"""

    def __init__(self):
        """Initialize GCP Pricing client"""
        logger.warning("GCP pricing integration is currently disabled")
        self.enabled = False

    def fetch_all_pricing(self) -> List[Dict]:
        """
        Fetch all pricing data (Database, Compute, Storage)

        Returns:
            Empty list (disabled for now)
        """
        logger.info("GCP pricing fetch skipped - integration disabled")
        return []


# Convenience function
def fetch_gcp_pricing() -> List[Dict]:
    """
    Convenience function to fetch GCP pricing

    Returns:
        Empty list (disabled for now)
    """
    logger.info("GCP pricing temporarily disabled - will be implemented with credentials")
    return []


# TODO: Implement when GCP credentials are available
# from google.cloud import billing_v1
# from google.oauth2 import service_account
#
# def fetch_gcp_pricing_impl():
#     """Full implementation with GCP client library"""
#     credentials = service_account.Credentials.from_service_account_file(
#         config.GCP_SERVICE_ACCOUNT_FILE
#     )
#     client = billing_v1.CloudCatalogClient(credentials=credentials)
#     # ... implementation
