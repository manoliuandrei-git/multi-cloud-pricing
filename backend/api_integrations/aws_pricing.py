"""
AWS Pricing Integration
Fetches pricing data from Amazon Web Services

Note: Temporarily disabled - large JSON downloads (400MB+) make real-time
fetching impractical. Will be re-implemented with a caching strategy
(local cache or OCI Object Storage external table).
"""
from typing import List, Dict
from utils.logger import get_logger

logger = get_logger(__name__)


class AWSPricingClient:
    """Client for AWS Pricing API"""

    def __init__(self):
        """Initialize AWS Pricing client"""
        logger.warning("AWS pricing integration is currently disabled")
        self.enabled = False

    def fetch_all_pricing(self) -> List[Dict]:
        """
        Fetch all pricing data (Database, Compute, Storage)

        Returns:
            Empty list (disabled for now)
        """
        logger.info("AWS pricing fetch skipped - integration disabled")
        return []

    def get_rds_pricing(self) -> List[Dict]:
        """Placeholder - returns empty list"""
        logger.info("AWS RDS pricing fetch skipped - integration disabled")
        return []

    def get_ec2_pricing(self) -> List[Dict]:
        """Placeholder - returns empty list"""
        logger.info("AWS EC2 pricing fetch skipped - integration disabled")
        return []

    def get_s3_pricing(self) -> List[Dict]:
        """Placeholder - returns empty list"""
        logger.info("AWS S3 pricing fetch skipped - integration disabled")
        return []


# Convenience function
def fetch_aws_pricing() -> List[Dict]:
    """
    Convenience function to fetch AWS pricing

    Returns:
        Empty list (disabled for now)
    """
    logger.info("AWS pricing temporarily disabled - caching strategy pending")
    return []


# TODO: Re-implement when caching strategy is in place
# Options under consideration:
#   A) Local file cache - download once, reuse for 24h
#   B) OCI Object Storage + Oracle External Table - store JSON in bucket,
#      query directly from ATP without Python parsing overhead
#
# Public pricing endpoints (no credentials needed):
#   RDS:  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/index.json
#   EC2:  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/index.json
#   S3:   https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/index.json
#
# Full implementation preserved in: api_integrations/aws_pricing_old.py
