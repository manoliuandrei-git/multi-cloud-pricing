"""
Configuration Management for Multi-Cloud Pricing Calculator
Loads environment variables and provides configuration settings
"""
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration class"""

    # Project Paths
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"
    CACHE_DIR = DATA_DIR / "cache"
    LOGS_DIR = BASE_DIR / "logs"

    # Oracle ATP Configuration
    ATP_USERNAME = os.getenv("ATP_USERNAME", "ADMIN")
    ATP_PASSWORD = os.getenv("ATP_PASSWORD", "")
    ATP_SERVICE = os.getenv("ATP_SERVICE", "xhbn5azdba5w4qmn_high")
    ATP_WALLET_DIR = os.getenv("ATP_WALLET_DIR", "./atpwallet")
    ATP_CONFIG_DIR = os.getenv("ATP_CONFIG_DIR", "./atpwallet")

    @property
    def atp_dsn(self) -> str:
        """Generate ATP DSN connection string"""
        return f"{self.ATP_SERVICE}"

    # Anthropic API Configuration
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # GCP Configuration
    GCP_SERVICE_ACCOUNT_FILE = os.getenv("GCP_SERVICE_ACCOUNT_FILE", "")
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")

    # OCI Object Storage Configuration
    OCI_BUCKET_NAME = os.getenv("OCI_BUCKET_NAME", "")
    OCI_NAMESPACE = os.getenv("OCI_NAMESPACE", "")
    OCI_REGION = os.getenv("OCI_REGION", "eu-zurich-1")
    OCI_CREDENTIAL_NAME = os.getenv("OCI_CREDENTIAL_NAME", "OBJ_STORE_CRED")

    # Cloud Provider Regions
    TARGET_REGIONS = os.getenv("TARGET_REGIONS", "eu-central-1,eu-west-1,eu-west-2,europe-west1,europe-west2,westeurope,northeurope").split(",")

    # Region Mappings for Different Cloud Providers
    REGION_MAPPING = {
        "aws": {
            "frankfurt": "eu-central-1",
            "london": "eu-west-2",
            "paris": "eu-west-3",
            "amsterdam": "eu-west-1"
        },
        "azure": {
            "frankfurt": "germanywestcentral",
            "london": "uksouth",
            "paris": "francecentral",
            "amsterdam": "westeurope"
        },
        "gcp": {
            "frankfurt": "europe-west3",
            "london": "europe-west2",
            "paris": "europe-west9",
            "amsterdam": "europe-west4"
        },
        "oci": {
            "frankfurt": "eu-frankfurt-1",
            "london": "uk-london-1",
            "paris": "eu-paris-1",
            "amsterdam": "eu-amsterdam-1",
            "zurich": "eu-zurich-1"
        }
    }

    # Scheduler Configuration
    PRICING_REFRESH_TIME = os.getenv("PRICING_REFRESH_TIME", "09:00")
    PRICING_REFRESH_TIMEZONE = os.getenv("PRICING_REFRESH_TIMEZONE", "local")

    # Application Configuration
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "True").lower() == "true"

    # Vector Search Configuration
    VECTOR_SEARCH_ENABLED = os.getenv("VECTOR_SEARCH_ENABLED", "False").lower() == "true"
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "DOC_MODEL")
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))
    VECTOR_DISTANCE_METRIC = os.getenv("VECTOR_DISTANCE_METRIC", "COSINE")

    # Service Categories
    SERVICE_CATEGORIES: List[str] = os.getenv("SERVICE_CATEGORIES", "Database,Compute,Storage").split(",")

    # Database Table Names
    TABLE_PRICING_CACHE = "pricing_cache"
    TABLE_PRICING_HISTORY = "pricing_cache_history"
    TABLE_SERVICE_MAPPINGS = "service_mappings"
    TABLE_OCI_PRICING_DOCS = "oci_pricing_docs"
    TABLE_DOC_CHUNKS = "doc_chunks"
    TABLE_LOG_AGENTS = "log_agents"

    @classmethod
    def validate(cls) -> List[str]:
        """Validate configuration and return list of missing required fields"""
        missing = []

        if not cls.ATP_PASSWORD:
            missing.append("ATP_PASSWORD")
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if not cls.OCI_BUCKET_NAME:
            missing.append("OCI_BUCKET_NAME")
        if not cls.OCI_NAMESPACE:
            missing.append("OCI_NAMESPACE")

        return missing

    @classmethod
    def create_directories(cls):
        """Create necessary directories if they don't exist"""
        cls.DATA_DIR.mkdir(exist_ok=True)
        cls.CACHE_DIR.mkdir(exist_ok=True)
        cls.LOGS_DIR.mkdir(exist_ok=True)


# Create configuration instance
config = Config()

# Create directories on import
config.create_directories()
