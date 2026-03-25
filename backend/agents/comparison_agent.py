"""
Comparison Agent
Synthesizes pricing data across cloud providers and generates recommendations
"""
import json
from typing import Dict, List
from agents.base_agent import BaseAgent
from utils.logger import get_logger

logger = get_logger(__name__)


class ComparisonAgent(BaseAgent):
    """Agent for comparing and recommending cloud services"""

    def __init__(self):
        super().__init__(name="ComparisonAgent", agent_type="comparison")

    def execute(self, input_data: Dict) -> Dict:
        """
        Execute comparison and generate recommendations

        Args:
            input_data: Dict with keys:
                - services: List of service pricing data from all providers
                - user_requirements: Original user requirements
                - user_input: Original user input text

        Returns:
            Dict with comparison results and recommendations
        """
        services = input_data.get('services', [])
        user_requirements = input_data.get('user_requirements', {})
        user_input = input_data.get('user_input', '')

        if not services:
            return {
                'comparison': [],
                'recommendations': [],
                'reasoning': 'No services available for comparison'
            }

        self.logger.info(f"Comparing {len(services)} services")

        # Sort services by price
        services_sorted = sorted(services, key=lambda x: x.get('price_per_month', 999999))

        # Generate comparison with Claude
        comparison_result = self._generate_comparison(
            services_sorted,
            user_requirements,
            user_input
        )

        return {
            'comparison': services_sorted,
            'recommendations': comparison_result.get('recommendations', []),
            'summary': comparison_result.get('summary', ''),
            'reasoning': comparison_result.get('reasoning', ''),
            'best_value': comparison_result.get('best_value'),
            'cheapest': services_sorted[0] if services_sorted else None,
            'price_range': {
                'min': services_sorted[0].get('price_per_month') if services_sorted else 0,
                'max': services_sorted[-1].get('price_per_month') if services_sorted else 0
            }
        }

    def _generate_comparison(
        self,
        services: List[Dict],
        user_requirements: Dict,
        user_input: str
    ) -> Dict:
        """
        Use Claude to generate intelligent comparison and recommendations

        Args:
            services: List of service pricing data (sorted by price)
            user_requirements: Structured requirements
            user_input: Original user input

        Returns:
            Dict with comparison analysis
        """
        # Limit to top 20 services to avoid token limits
        top_services = services[:20]

        system_prompt = """You are a cloud pricing and architecture expert. Given a list of cloud services
from different providers (AWS, Azure, GCP, OCI) and user requirements, provide:

1. Top 3 recommendations with explanations
2. A brief summary comparing the options
3. Key insights about pricing differences
4. Best value recommendation (not just cheapest)

Return a JSON object with these fields:
- recommendations: Array of top 3 services with 'service_info' and 'reason' for each
  * First should be best value (not cheapest)
  * Second should be most feature-rich
  * Third should be cheapest option

Consider factors like:
- Price (30% weight)
- Performance (25% weight)
- Features and capabilities (20% weight)
- Provider ecosystem (15% weight)
- Regional availability (10% weight)"""

        services_json = json.dumps(top_services, default=str, indent=2)

        user_message = f"""User Requirements:
{json.dumps(user_requirements, indent=2)}

Original User Input: {user_input}

Available Services (sorted by price):
{services_json}

Provide your comparison analysis and recommendations."""

        messages = [{'role': 'user', 'content': user_message}]

        try:
            response = self.call_claude(messages=messages, system=system_prompt, max_tokens=3000)
            response_text = self.extract_text_response(response)

            # Extract JSON
            comparison_result = self.extract_json_from_response(response_text)

            if comparison_result:
                self.logger.info("Generated comparison with recommendations")
                return comparison_result
            else:
                # Fallback to basic comparison
                self.logger.warning("Failed to parse Claude response, using fallback")
                return self._fallback_comparison(top_services)

        except Exception as e:
            self.logger.error(f"Failed to generate comparison with Claude: {e}")
            return self._fallback_comparison(top_services)

    def _fallback_comparison(self, services: List[Dict]) -> Dict:
        """
        Fallback comparison when Claude is unavailable

        Args:
            services: List of services (sorted by price)

        Returns:
            Dict with basic comparison
        """
        if not services:
            return {
                'recommendations': [],
                'summary': 'No services available for comparison',
                'reasoning': '',
                'best_value': None,
                'insights': []
            }

        # Group by provider
        by_provider = {}
        for service in services:
            provider = service.get('cloud_provider', 'Unknown')
            if provider not in by_provider:
                by_provider[provider] = []
            by_provider[provider].append(service)

        # Get cheapest per provider
        cheapest_per_provider = {}
        for provider, provider_services in by_provider.items():
            if provider_services:
                cheapest_per_provider[provider] = min(
                    provider_services,
                    key=lambda x: x.get('price_per_month', 999999)
                )

        # Top 3 cheapest overall
        top_3 = services[:3]

        recommendations = [
            {
                'service_info': service,
                'reason': f"${service.get('price_per_month', 0):.2f}/month - Competitive pricing"
            }
            for service in top_3
        ]

        summary = f"Found {len(services)} services across {len(by_provider)} cloud providers. "
        summary += f"Prices range from ${services[0].get('price_per_month', 0):.2f} to ${services[-1].get('price_per_month', 0):.2f} per month."

        return {
            'recommendations': recommendations,
            'summary': summary,
            'reasoning': 'Basic price-based comparison (AI analysis unavailable)',
            'best_value': services[0] if services else None,
            'insights': [
                f"Cheapest option: {services[0].get('cloud_provider')} - {services[0].get('service_name')} at ${services[0].get('price_per_month', 0):.2f}/month"
            ]
        }

    def generate_comparison_table(self, services: List[Dict]) -> str:
        """
        Generate a formatted comparison table

        Args:
            services: List of service pricing data

        Returns:
            Formatted table string
        """
        if not services:
            return "No services to compare"

        # Header
        table = "| Provider | Service | Instance Type | Region | Price/Month |\n"
        table += "|----------|---------|---------------|--------|-------------|\n"

        # Rows
        for service in services[:20]:  # Limit to 20 rows
            provider = service.get('cloud_provider', 'N/A')
            service_name = service.get('service_name', 'N/A')
            instance_type = service.get('instance_type', 'N/A')
            region = service.get('region', 'N/A')
            price = service.get('price_per_month', 0)

            table += f"| {provider} | {service_name} | {instance_type} | {region} | ${price:.2f} |\n"

        return table


# Convenience function
def compare_services(services: List[Dict], user_requirements: Dict = None, user_input: str = '') -> Dict:
    """
    Convenience function to compare services

    Args:
        services: List of service pricing data
        user_requirements: User requirements
        user_input: Original user input

    Returns:
        Dict with comparison results
    """
    agent = ComparisonAgent()
    return agent.run({
        'services': services,
        'user_requirements': user_requirements or {},
        'user_input': user_input
    })
