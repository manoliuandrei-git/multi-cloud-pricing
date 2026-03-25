"""
Base Agent Class
Provides common functionality for all AI agents
"""
import time
import json
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from anthropic import Anthropic
from config import config
from database.queries import log_agent_execution
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Base class for all AI agents"""

    def __init__(self, name: str, agent_type: str):
        """
        Initialize base agent

        Args:
            name: Agent name
            agent_type: Agent type (mapping, pricing, comparison)
        """
        self.name = name
        self.agent_type = agent_type
        self.client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.ANTHROPIC_MODEL
        self.logger = get_logger(f"agents.{name}")

    @abstractmethod
    def execute(self, input_data: Dict) -> Dict:
        """
        Execute agent logic

        Args:
            input_data: Input data dictionary

        Returns:
            Dict with agent output
        """
        pass

    def run(self, input_data: Dict) -> Dict:
        """
        Run the agent with logging and error handling

        Args:
            input_data: Input data dictionary

        Returns:
            Dict with agent output and metadata
        """
        start_time = time.time()
        status = 'SUCCESS'
        error_message = None
        output_data = {}
        context = {}

        try:
            self.logger.info(f"Agent {self.name} starting execution")

            # Execute agent logic
            output_data = self.execute(input_data)

            # Add metadata
            output_data['_metadata'] = {
                'agent_name': self.name,
                'agent_type': self.agent_type,
                'execution_time_ms': int((time.time() - start_time) * 1000),
                'status': status
            }

        except Exception as e:
            status = 'FAILURE'
            error_message = str(e)
            self.logger.error(f"Agent {self.name} failed: {e}", exc_info=True)

            output_data = {
                'error': error_message,
                '_metadata': {
                    'agent_name': self.name,
                    'agent_type': self.agent_type,
                    'execution_time_ms': int((time.time() - start_time) * 1000),
                    'status': status
                }
            }

        finally:
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Log to database
            try:
                log_agent_execution(
                    agent_name=self.name,
                    agent_type=self.agent_type,
                    input_data=input_data,
                    output_data=output_data,
                    context=context,
                    decision_reasoning=output_data.get('reasoning', ''),
                    execution_time_ms=execution_time_ms,
                    status=status,
                    error_message=error_message,
                    api_calls_made=output_data.get('_metadata', {}).get('api_calls', 0),
                    tokens_used=output_data.get('_metadata', {}).get('tokens_used', 0)
                )
            except Exception as log_error:
                self.logger.warning(f"Failed to log agent execution: {log_error}")

        return output_data

    def call_claude(
        self,
        messages: List[Dict],
        system: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        max_tokens: int = 4096
    ) -> Dict:
        """
        Call Claude API with messages

        Args:
            messages: List of message dictionaries
            system: Optional system prompt
            tools: Optional list of tool definitions
            max_tokens: Maximum tokens in response

        Returns:
            Dict with response data
        """
        try:
            params = {
                'model': self.model,
                'max_tokens': max_tokens,
                'messages': messages
            }

            if system:
                params['system'] = system

            if tools:
                params['tools'] = tools

            response = self.client.messages.create(**params)

            # Extract response data
            result = {
                'content': [],
                'stop_reason': response.stop_reason,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }
            }

            # Process content blocks
            for block in response.content:
                if block.type == 'text':
                    result['content'].append({
                        'type': 'text',
                        'text': block.text
                    })
                elif block.type == 'tool_use':
                    result['content'].append({
                        'type': 'tool_use',
                        'id': block.id,
                        'name': block.name,
                        'input': block.input
                    })

            return result

        except Exception as e:
            self.logger.error(f"Claude API call failed: {e}")
            raise

    def extract_text_response(self, claude_response: Dict) -> str:
        """
        Extract text from Claude response

        Args:
            claude_response: Response from call_claude

        Returns:
            Extracted text
        """
        text_parts = []

        for content_block in claude_response.get('content', []):
            if content_block.get('type') == 'text':
                text_parts.append(content_block.get('text', ''))

        return '\n'.join(text_parts)

    def extract_json_from_response(self, text: str) -> Optional[Dict]:
        """
        Extract JSON from text response

        Args:
            text: Text that may contain JSON

        Returns:
            Parsed JSON dict or None
        """
        try:
            # Try to parse entire text as JSON
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in ```json``` blocks
            import re
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Try to find any JSON object
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

        return None

    def format_pricing_data(self, pricing_list: List[Dict]) -> str:
        """
        Format pricing data for Claude

        Args:
            pricing_list: List of pricing dictionaries

        Returns:
            Formatted string
        """
        if not pricing_list:
            return "No pricing data available"

        formatted = []
        for i, item in enumerate(pricing_list, 1):
            formatted.append(
                f"{i}. {item.get('cloud_provider')} - {item.get('service_name')} "
                f"({item.get('instance_type')})\n"
                f"   Region: {item.get('region')}\n"
                f"   Price: ${item.get('price_per_month', 0):.2f}/month\n"
                f"   Specs: {json.dumps(item.get('specifications', {}), indent=2)}"
            )

        return '\n\n'.join(formatted)
