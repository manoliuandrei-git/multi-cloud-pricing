"""
OCI Pricing Agent
Uses RAG (Retrieval Augmented Generation) to extract OCI pricing from documentation
"""
import json
from typing import Dict, List
from agents.base_agent import BaseAgent
from utils.vector_utils import query_vector_search
from utils.logger import get_logger

logger = get_logger(__name__)


class OCIPricingAgent(BaseAgent):
    """Agent for extracting OCI pricing using RAG"""

    def __init__(self):
        super().__init__(name="OCIPricingAgent", agent_type="oci_pricing")

    def execute(self, input_data: Dict) -> Dict:
        """
        Execute OCI pricing extraction

        Args:
            input_data: Dict with keys:
                - service_type: Type of OCI service
                - service_category: Database, Compute, or Storage
                - specifications: Dict of technical specs (optional)
                - region: OCI region (optional)

        Returns:
            Dict with OCI pricing information
        """
        service_type = input_data.get('service_type', '')
        service_category = input_data.get('service_category', 'Database')
        specifications = input_data.get('specifications', {})
        region = input_data.get('region', 'eu-zurich-1')

        self.logger.info(f"Extracting OCI pricing for {service_type} in {region}")

        # Step 1: Generate search queries for vector search
        search_queries = self._generate_search_queries(service_type, service_category, specifications)

        # Step 2: Retrieve relevant document chunks using vector search
        # min_similarity=0.3 is intentionally permissive — the PDF may use different
        # terminology than the search query, so we cast a wider net and let Claude
        # decide whether the chunk contains relevant pricing.
        relevant_chunks = []
        for query in search_queries:
            chunks = query_vector_search(query, top_k=5, min_similarity=0.3)
            relevant_chunks.extend(chunks)

        # Remove duplicates based on chunk_text
        unique_chunks = []
        seen_texts = set()
        for chunk in relevant_chunks:
            chunk_text = chunk.get('chunk_text', '')
            if chunk_text not in seen_texts:
                unique_chunks.append(chunk)
                seen_texts.add(chunk_text)

        self.logger.info(f"Retrieved {len(unique_chunks)} unique relevant chunks")

        # Step 3: Use Claude to extract pricing information
        pricing_info = self._extract_pricing_from_chunks(
            unique_chunks,
            service_type,
            service_category,
            specifications,
            region
        )

        return {
            'pricing_info': pricing_info,
            'sources': [
                {
                    'document': chunk.get('document_name'),
                    'similarity': chunk.get('similarity_score')
                }
                for chunk in unique_chunks[:5]
            ],
            'reasoning': f"Extracted OCI pricing from {len(unique_chunks)} document chunks",
            'chunks_analyzed': len(unique_chunks)
        }

    def _generate_search_queries(
        self,
        service_type: str,
        service_category: str,
        specifications: Dict
    ) -> List[str]:
        """
        Generate search queries for vector search

        Args:
            service_type: Type of service
            service_category: Service category
            specifications: Technical specifications

        Returns:
            List of search query strings
        """
        queries = [
            f"OCI {service_category} {service_type} pricing",
            f"Oracle Cloud {service_type} price per month",
            f"OCI {service_type} cost",
            f"{service_type} OCPU per hour price",
            f"Oracle {service_category} pricing USD",
        ]

        # Add specification-based queries
        if specifications.get('vcpu'):
            queries.append(f"OCI {service_type} {specifications['vcpu']} vCPU pricing")

        if specifications.get('memory_gb'):
            queries.append(f"OCI {service_type} {specifications['memory_gb']} GB memory pricing")

        if specifications.get('storage_gb'):
            queries.append(f"OCI {service_type} {specifications['storage_gb']} GB storage pricing")

        self.logger.info(f"Generated {len(queries)} search queries")
        return queries

    def _extract_pricing_from_chunks(
        self,
        chunks: List[Dict],
        service_type: str,
        service_category: str,
        specifications: Dict,
        region: str
    ) -> Dict:
        """
        Use Claude to extract structured pricing from document chunks

        Args:
            chunks: List of relevant document chunks
            service_type: Type of service
            service_category: Service category
            specifications: Technical specifications
            region: OCI region

        Returns:
            Dict with structured pricing information
        """
        if not chunks:
            self.logger.warning("No document chunks available for pricing extraction")
            return {
                'service_name': f"OCI {service_type}",
                'price_per_month': 0,
                'price_per_hour': 0,
                'currency': 'USD',
                'error': 'No pricing documentation found'
            }

        # Prepare context from chunks
        context = "\n\n---\n\n".join([
            f"Source: {chunk.get('document_name')}\n"
            f"Similarity: {chunk.get('similarity_score', 0):.2f}\n"
            f"Content:\n{chunk.get('chunk_text', '')}"
            for chunk in chunks[:10]  # Use top 10 chunks
        ])

        system_prompt = """You are an Oracle Cloud Infrastructure (OCI) pricing expert. Given documentation excerpts, extract structured pricing information for the requested service.

Return a JSON object with these fields:
- service_name: Official OCI service name (string)
- instance_type: Instance type or SKU if available, otherwise "Standard" (string)
- price_per_hour: Hourly price as a number. If pricing is per OCPU/hour, use that rate. If only monthly is available, divide by 730. Use 0 if truly unknown.
- price_per_month: Monthly price as a number. If pricing is per OCPU/month, use that rate. If only hourly is available, multiply by 730. Use 0 if truly unknown.
- currency: Currency code, usually "USD" (string)
- specifications: Dict of technical specs such as ocpu, memory_gb, storage_gb, etc. (object)
- features: List of key features as strings (array)
- pricing_model: "Pay As You Go", "Monthly Flex", "Annual Universal Credits", etc. (string)
- notes: Any important pricing notes, conditions or caveats (string)

IMPORTANT:
- OCI often prices by OCPU (Oracle CPU). Use the per-OCPU rate as price_per_hour.
- Always return a valid JSON object even if pricing data is incomplete — use 0 for unknown numeric fields.
- Do NOT include an "error" field unless no pricing-related content was found at all.
- "features" must always be a JSON array of strings, never a plain string."""

        user_message = f"""Service Category: {service_category}
Service Type: {service_type}
Required Specifications: {json.dumps(specifications)}
Region: {region}

Documentation Context:
{context}

Extract the OCI pricing information for this service. Be precise with numbers."""

        messages = [{'role': 'user', 'content': user_message}]

        try:
            response = self.call_claude(messages=messages, system=system_prompt, max_tokens=3000)
            response_text = self.extract_text_response(response)

            # Extract JSON
            pricing_info = self.extract_json_from_response(response_text)

            if pricing_info:
                self.logger.info(f"Extracted OCI pricing: {pricing_info.get('service_name')}")
                return pricing_info
            else:
                self.logger.warning("Failed to parse pricing JSON from Claude response")
                return {
                    'service_name': f"OCI {service_type}",
                    'price_per_month': None,
                    'error': 'Failed to parse pricing information'
                }

        except Exception as e:
            self.logger.error(f"Failed to extract pricing with Claude: {e}")
            return {
                'service_name': f"OCI {service_type}",
                'price_per_month': None,
                'error': str(e)
            }

    def extract_multiple_oci_services(
        self,
        service_category: str,
        service_types: List[str],
        region: str = 'eu-zurich-1'
    ) -> List[Dict]:
        """
        Extract pricing for multiple OCI services

        Args:
            service_category: Service category
            service_types: List of service types
            region: OCI region

        Returns:
            List of pricing dictionaries
        """
        results = []

        for service_type in service_types:
            try:
                result = self.run({
                    'service_type': service_type,
                    'service_category': service_category,
                    'region': region
                })

                pricing = result.get('pricing_info', {})
                # Include the record as long as we got some response from Claude.
                # Records with no useful price will have 0s (set by queries.py sanitiser).
                # Only skip if pricing dict is empty or has an explicit error with no data.
                if pricing and pricing.get('service_name'):
                    features = pricing.get('features', [])
                    # Ensure features is always a list of strings
                    if isinstance(features, str):
                        features = [features] if features else []
                    elif not isinstance(features, list):
                        features = []

                    formatted = {
                        'cloud_provider': 'OCI',
                        'service_category': service_category,
                        'service_name': pricing.get('service_name', service_type),
                        'instance_type': pricing.get('instance_type', 'Standard'),
                        'region': region,
                        'price_per_hour': pricing.get('price_per_hour') or 0.0,
                        'price_per_month': pricing.get('price_per_month') or 0.0,
                        'currency': pricing.get('currency', 'USD'),
                        'specifications': pricing.get('specifications', {}),
                        'features': features,
                        'source_api': 'OCI Documentation RAG'
                    }
                    results.append(formatted)
                    if pricing.get('error'):
                        self.logger.warning(
                            f"Pricing for {service_type} has error: {pricing['error']} "
                            f"— inserted with 0 prices"
                        )

            except Exception as e:
                self.logger.error(f"Failed to extract pricing for {service_type}: {e}")
                continue

        self.logger.info(f"Extracted pricing for {len(results)} OCI services")
        return results


# Convenience function
def extract_oci_pricing(service_type: str, service_category: str, specifications: Dict = None, region: str = 'eu-zurich-1') -> Dict:
    """
    Convenience function to extract OCI pricing

    Args:
        service_type: Type of OCI service
        service_category: Service category
        specifications: Optional technical specifications
        region: OCI region

    Returns:
        Dict with OCI pricing information
    """
    agent = OCIPricingAgent()
    return agent.run({
        'service_type': service_type,
        'service_category': service_category,
        'specifications': specifications or {},
        'region': region
    })
