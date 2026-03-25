"""
Azure Retail Prices API Integration
Fetches pricing data from Azure Retail Prices REST API
"""
import requests
from typing import List, Dict, Optional
from datetime import datetime
from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def _infer_azure_billing_type(unit_of_measure: str, service_category: str = '') -> str:
    """
    Derive a short billing-type category from the Azure unitOfMeasure field.

    Azure unitOfMeasure examples:
        "1 Hour"            → Compute
        "10 Hours"          → Compute
        "1 GB/Month"        → Storage
        "1 GB"              → Storage
        "1 TB/Month"        → Storage
        "10,000"            → API/Request
        "1 Million"         → API/Request
        "1 Unit"            → Other (falls back to service_category)
        "1 /Month"          → Other
    """
    low = (unit_of_measure or '').lower().strip()

    if 'hour' in low:
        return 'Compute'

    if any(kw in low for kw in ('gb/month', 'gb', 'tb/month', 'tb',
                                  'gigabyte', 'terabyte', 'storage')):
        return 'Storage'

    if any(kw in low for kw in ('transfer', 'bandwidth', 'egress', 'ingress')):
        return 'Network'

    if any(kw in low for kw in ('million', '10,000', '1,000', 'request',
                                  'transaction', 'query', 'call', 'message')):
        return 'API/Request'

    if 'license' in low or 'byol' in low:
        return 'License'

    if 'support' in low:
        return 'Support'

    # Fall back to the service category (Database, Compute, Storage, …)
    return service_category or 'Other'


class AzurePricingClient:
    """Client for Azure Retail Prices API"""

    BASE_URL = "https://prices.azure.com/api/retail/prices"

    def __init__(self):
        """Initialize Azure Pricing client"""
        self.session = requests.Session()
        self.target_regions = [
            'westeurope',
            'northeurope',
            'germanywestcentral',
            'uksouth',
            'francecentral'
        ]

    def _make_request(self, params: Dict) -> Optional[Dict]:
        """
        Make API request to Azure Retail Prices API

        Args:
            params: Query parameters

        Returns:
            API response dictionary or None
        """
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Azure API request failed: {e}")
            return None

    def get_database_pricing(self, regions: Optional[List[str]] = None) -> List[Dict]:
        """
        Get Azure Database pricing (SQL Database, MySQL, PostgreSQL)

        Args:
            regions: List of Azure regions

        Returns:
            List of pricing dictionaries
        """
        if regions is None:
            regions = self.target_regions

        pricing_data = []

        for region in regions:
            logger.info(f"Fetching Azure Database pricing for region: {region}")

            # SQL Database
            sql_filter = f"serviceName eq 'SQL Database' and armRegionName eq '{region}' and priceType eq 'Consumption'"
            sql_pricing = self._fetch_with_filter(sql_filter, region, 'Database', 'SQL Database')
            pricing_data.extend(sql_pricing[:20])  # Limit results

            # MySQL
            mysql_filter = f"serviceName eq 'Azure Database for MySQL' and armRegionName eq '{region}' and priceType eq 'Consumption'"
            mysql_pricing = self._fetch_with_filter(mysql_filter, region, 'Database', 'MySQL Database')
            pricing_data.extend(mysql_pricing[:10])

            # PostgreSQL
            pg_filter = f"serviceName eq 'Azure Database for PostgreSQL' and armRegionName eq '{region}' and priceType eq 'Consumption'"
            pg_pricing = self._fetch_with_filter(pg_filter, region, 'Database', 'PostgreSQL Database')
            pricing_data.extend(pg_pricing[:10])

        logger.info(f"Fetched {len(pricing_data)} Azure Database pricing records")
        return pricing_data

    def get_compute_pricing(self, regions: Optional[List[str]] = None) -> List[Dict]:
        """
        Get Azure Virtual Machines pricing

        Args:
            regions: List of Azure regions

        Returns:
            List of pricing dictionaries
        """
        if regions is None:
            regions = self.target_regions

        pricing_data = []

        for region in regions:
            logger.info(f"Fetching Azure VM pricing for region: {region}")

            # Virtual Machines - General Purpose (D-series)
            vm_filter = f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' and priceType eq 'Consumption' and contains(productName, 'D') and contains(productName, 'v')"
            vm_pricing = self._fetch_with_filter(vm_filter, region, 'Compute', 'Virtual Machines')
            pricing_data.extend(vm_pricing[:30])  # Get more VM options

        logger.info(f"Fetched {len(pricing_data)} Azure VM pricing records")
        return pricing_data

    def get_storage_pricing(self, regions: Optional[List[str]] = None) -> List[Dict]:
        """
        Get Azure Blob Storage pricing

        Args:
            regions: List of Azure regions

        Returns:
            List of pricing dictionaries
        """
        if regions is None:
            regions = self.target_regions

        pricing_data = []

        for region in regions:
            logger.info(f"Fetching Azure Storage pricing for region: {region}")

            # Blob Storage - Hot tier
            storage_filter = f"serviceName eq 'Storage' and armRegionName eq '{region}' and priceType eq 'Consumption' and contains(productName, 'Hot')"
            storage_pricing = self._fetch_with_filter(storage_filter, region, 'Storage', 'Blob Storage')
            pricing_data.extend(storage_pricing[:10])

        logger.info(f"Fetched {len(pricing_data)} Azure Storage pricing records")
        return pricing_data

    def _fetch_with_filter(
        self,
        filter_query: str,
        region: str,
        category: str,
        service_name: str,
        max_results: int = 100
    ) -> List[Dict]:
        """
        Fetch pricing data with a specific filter

        Args:
            filter_query: OData filter string
            region: Azure region
            category: Service category
            service_name: Service name
            max_results: Maximum number of results

        Returns:
            List of pricing dictionaries
        """
        pricing_data = []

        try:
            params = {
                '$filter': filter_query,
                'api-version': '2023-01-01-preview'
            }

            next_url = None
            page_count = 0
            max_pages = 3  # Limit to 3 pages to avoid excessive API calls

            while page_count < max_pages:
                if next_url:
                    response = self.session.get(next_url, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                else:
                    data = self._make_request(params)

                if not data:
                    break

                items = data.get('Items', [])

                for item in items:
                    parsed = self._parse_azure_pricing(item, region, category, service_name)
                    if parsed:
                        pricing_data.append(parsed)

                    if len(pricing_data) >= max_results:
                        break

                if len(pricing_data) >= max_results:
                    break

                # Check for next page
                next_url = data.get('NextPageLink')
                if not next_url:
                    break

                page_count += 1

        except Exception as e:
            logger.error(f"Failed to fetch Azure pricing with filter: {e}")

        return pricing_data

    def _parse_azure_pricing(
        self,
        item: Dict,
        region: str,
        category: str,
        service_name: str
    ) -> Optional[Dict]:
        """
        Parse Azure pricing item

        Args:
            item: Azure pricing item
            region: Azure region
            category: Service category
            service_name: Service name

        Returns:
            Parsed pricing dictionary or None
        """
        try:
            retail_price = item.get('retailPrice', 0)
            if retail_price == 0:
                return None

            # Most Azure prices are per hour
            price_per_hour = float(retail_price)
            price_per_month = round(price_per_hour * 730, 2)

            # Extract key fields
            product_name     = item.get('productName', '')
            sku_name         = item.get('skuName', '')
            meter_name       = item.get('meterName', '')
            unit_of_measure  = item.get('unitOfMeasure', '')

            # Build the human-readable metric string.
            # Prefer meterName (more descriptive) combined with unitOfMeasure.
            # e.g.  meterName="D2s v3"  uom="1 Hour"  → "D2s v3 / 1 Hour"
            if meter_name and unit_of_measure:
                metric = f"{meter_name} / {unit_of_measure}"
            elif meter_name:
                metric = meter_name
            elif unit_of_measure:
                metric = unit_of_measure
            else:
                metric = None

            # Derive billing-type category for instance_type
            billing_type = _infer_azure_billing_type(unit_of_measure, category)

            specs = {
                'product_name': product_name,
                'sku_name': sku_name,
                'meter_name': meter_name,
                'unit_of_measure': unit_of_measure,
                'tier_minimum_units': item.get('tierMinimumUnits', 0)
            }

            # Extract compute specs from product name if available
            if 'vCPU' in product_name:
                import re
                vcpu_match = re.search(r'(\d+)\s*vCPU', product_name)
                if vcpu_match:
                    specs['vcpu'] = int(vcpu_match.group(1))

            if 'GB' in product_name:
                import re
                mem_match = re.search(r'(\d+)\s*GB', product_name)
                if mem_match:
                    specs['memory_gb'] = int(mem_match.group(1))

            return {
                'cloud_provider': 'Azure',
                'service_category': category,
                'service_name': service_name,
                'instance_type': billing_type,       # billing-type category
                'metric': metric,                    # raw billing metric string
                'region': region,
                'price_per_hour': price_per_hour,
                'price_per_month': price_per_month,
                'currency': item.get('currencyCode', 'USD'),
                'specifications': specs,
                'features': product_name,
                'source_api': 'Azure Retail Prices API'
            }

        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse Azure pricing item: {e}")
            return None

    def fetch_all_pricing(self) -> List[Dict]:
        """
        Fetch all pricing data (Database, Compute, Storage)

        Returns:
            Combined list of all pricing data
        """
        all_pricing = []

        logger.info("Fetching all Azure pricing data...")

        # Fetch Database pricing
        all_pricing.extend(self.get_database_pricing())

        # Fetch Compute pricing
        all_pricing.extend(self.get_compute_pricing())

        # Fetch Storage pricing
        all_pricing.extend(self.get_storage_pricing())

        logger.info(f"Fetched total of {len(all_pricing)} Azure pricing records")
        return all_pricing


# Convenience function
def fetch_azure_pricing() -> List[Dict]:
    """
    Convenience function to fetch Azure pricing

    Returns:
        List of pricing dictionaries
    """
    client = AzurePricingClient()
    return client.fetch_all_pricing()
