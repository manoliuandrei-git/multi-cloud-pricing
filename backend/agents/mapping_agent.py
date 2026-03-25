"""
Service Mapping Agent
Maps user requirements to equivalent cloud services across AWS, Azure, GCP, and OCI
"""
import json
from typing import Dict, List
from agents.base_agent import BaseAgent
from database.queries import get_service_mapping, get_pricing_by_service
from utils.logger import get_logger

logger = get_logger(__name__)


class MappingAgent(BaseAgent):
    """Agent for mapping services across cloud providers"""

    def __init__(self):
        super().__init__(name="MappingAgent", agent_type="mapping")

    def execute(self, input_data: Dict) -> Dict:
        """
        Execute service mapping

        Args:
            input_data: Dict with keys:
                - user_input: User's service requirements (str)
                - service_category: Database, Compute, or Storage
                - specifications: Dict of technical specs (optional)

        Returns:
            Dict with mapped services
        """
        user_input = input_data.get('user_input', '')
        service_category = input_data.get('service_category', 'Database')
        specifications = input_data.get('specifications', {})

        self.logger.info(f"Mapping services for category: {service_category}")

        # Step 1: Understand user requirements using Claude
        requirements = self._understand_requirements(user_input, service_category, specifications)

        # Step 2: Find matching services from pricing cache
        matching_services = self._find_matching_services(requirements, service_category)

        # Step 3: Use Claude to rank and filter services
        filtered_services = self._filter_and_rank_services(
            matching_services,
            requirements,
            user_input
        )

        return {
            'requirements': requirements,
            'matched_services': filtered_services,
            'reasoning': f"Found {len(filtered_services)} matching services across cloud providers",
            'service_count': {
                'aws': len([s for s in filtered_services if s.get('cloud_provider') == 'AWS']),
                'azure': len([s for s in filtered_services if s.get('cloud_provider') == 'Azure']),
                'gcp': len([s for s in filtered_services if s.get('cloud_provider') == 'GCP']),
                'oci': len([s for s in filtered_services if s.get('cloud_provider') == 'OCI'])
            }
        }

    def _understand_requirements(
        self,
        user_input: str,
        service_category: str,
        specifications: Dict
    ) -> Dict:
        """
        Use Claude to understand and structure user requirements

        Args:
            user_input: User's natural language input
            service_category: Service category
            specifications: Technical specifications

        Returns:
            Dict with structured requirements
        """
        system_prompt = """You are a cloud infrastructure expert. Your job is to understand user requirements
and extract key specifications for cloud services.

Analyze the user's input and extract:
1. Service type (e.g., MySQL database, virtual machine, object storage)
2. Technical specifications (CPU, memory, storage, etc.)
3. Performance requirements (high availability, IOPS, bandwidth)
4. Special features needed (backup, encryption, replication)

Return a JSON object with these structured requirements."""

        user_message = f"""Category: {service_category}
User Input: {user_input}
Provided Specifications: {json.dumps(specifications)}

Extract the key requirements and specifications."""

        messages = [{'role': 'user', 'content': user_message}]

        response = self.call_claude(messages=messages, system=system_prompt, max_tokens=2000)
        response_text = self.extract_text_response(response)

        # Try to extract JSON
        requirements = self.extract_json_from_response(response_text)

        if not requirements:
            # Fallback to basic requirements
            requirements = {
                'service_type': service_category,
                'specifications': specifications,
                'user_input': user_input
            }

        self.logger.info(f"Extracted requirements: {requirements}")
        return requirements

    def _find_matching_services(self, requirements: Dict, service_category: str) -> List[Dict]:
        """
        Find matching services from pricing cache

        Args:
            requirements: Structured requirements
            service_category: Service category

        Returns:
            List of matching service pricing data
        """
        try:
            # Query database for services in this category
            services = get_pricing_by_service(service_category=service_category)

            self.logger.info(f"Found {len(services)} services in category {service_category}")

            # Apply specification filters if provided
            specs = requirements.get('specifications', {})

            if specs:
                filtered = []
                for service in services:
                    service_specs = service.get('specifications', {})

                    # Parse specifications if it's a string
                    if isinstance(service_specs, str):
                        try:
                            service_specs = json.loads(service_specs)
                        except:
                            service_specs = {}

                    # Check if service meets requirements
                    meets_requirements = True

                    # Check vCPU
                    if 'vcpu' in specs and 'vcpu' in service_specs:
                        try:
                            required_vcpu = int(specs['vcpu'])
                            service_vcpu = int(str(service_specs['vcpu']).split()[0])  # Handle "4 vCPU" format
                            if service_vcpu < required_vcpu:
                                meets_requirements = False
                        except (ValueError, AttributeError):
                            pass

                    # Check memory
                    if 'memory_gb' in specs and ('memory' in service_specs or 'memory_gb' in service_specs):
                        try:
                            required_memory = int(specs['memory_gb'])
                            memory_str = service_specs.get('memory') or service_specs.get('memory_gb', '0')
                            service_memory = int(str(memory_str).split()[0])  # Handle "8 GB" format
                            if service_memory < required_memory:
                                meets_requirements = False
                        except (ValueError, AttributeError):
                            pass

                    if meets_requirements:
                        filtered.append(service)

                services = filtered
                self.logger.info(f"After filtering by specs: {len(services)} services")

            return services

        except Exception as e:
            self.logger.error(f"Failed to find matching services: {e}")
            return []

    def _filter_and_rank_services(
        self,
        services: List[Dict],
        requirements: Dict,
        user_input: str
    ) -> List[Dict]:
        """
        Use Claude to filter and rank services based on requirements

        Args:
            services: List of service pricing data
            requirements: Structured requirements
            user_input: Original user input

        Returns:
            Filtered and ranked list of services
        """
        if not services:
            return []

        # Limit to top 100 services to avoid token limits
        services = services[:100]

        system_prompt = """You are a cloud pricing expert. Given a list of cloud services and user requirements,
rank and filter the services by relevance and cost-effectiveness.

Return a JSON array of service objects, sorted by price (ascending), including only services that meet
the user's requirements. Each service should include a 'relevance_score' (0-100) and 'match_reason' explaining why it's a good match."""

        services_json = json.dumps(services, default=str)

        user_message = f"""User Requirements: {json.dumps(requirements)}
Original User Input: {user_input}

Available Services:
{services_json}

Filter and rank these services. Return top 30 most relevant services as a JSON array."""

        messages = [{'role': 'user', 'content': user_message}]

        try:
            response = self.call_claude(messages=messages, system=system_prompt, max_tokens=4096)
            response_text = self.extract_text_response(response)

            # Try to extract JSON
            ranked_services = self.extract_json_from_response(response_text)

            if ranked_services and isinstance(ranked_services, list):
                self.logger.info(f"Claude ranked {len(ranked_services)} services")
                return ranked_services[:30]  # Top 30 services
            else:
                # Fallback: return services sorted by price
                self.logger.warning("Failed to parse Claude response, using price-sorted fallback")
                return sorted(services, key=lambda x: x.get('price_per_month', 999999))[:30]

        except Exception as e:
            self.logger.error(f"Failed to rank services with Claude: {e}")
            # Fallback: return services sorted by price
            return sorted(services, key=lambda x: x.get('price_per_month', 999999))[:30]


# Convenience function
def map_services(user_input: str, service_category: str, specifications: Dict = None) -> Dict:
    """
    Convenience function to map services

    Args:
        user_input: User's service requirements
        service_category: Service category
        specifications: Optional technical specifications

    Returns:
        Dict with mapped services
    """
    agent = MappingAgent()
    return agent.run({
        'user_input': user_input,
        'service_category': service_category,
        'specifications': specifications or {}
    })
