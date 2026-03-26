"""
Common Database Queries
Provides reusable query functions for pricing cache, service mappings, and vector search
"""
import json
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date
from decimal import Decimal
from database.connection import db

logger = logging.getLogger(__name__)


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles Oracle-returned types (datetime, Decimal, bytes)."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


def _dumps(obj) -> str:
    """json.dumps with Oracle-safe encoder."""
    return _dumps(obj, cls=_SafeEncoder)


# ============================================
# PRICING CACHE QUERIES
# ============================================

def insert_pricing_data(pricing_data: Dict) -> int:
    """
    Insert or update pricing data in pricing_cache

    Args:
        pricing_data: Dictionary containing pricing information

    Returns:
        int: ID of inserted/updated row
    """
    query = """
        INSERT INTO pricing_cache (
            cloud_provider,
            service_category,
            service_name,
            instance_type,
            region,
            price_per_hour,
            price_per_month,
            currency,
            specifications,
            features,
            source_api
        ) VALUES (
            :cloud_provider,
            :service_category,
            :service_name,
            :instance_type,
            :region,
            :price_per_hour,
            :price_per_month,
            :currency,
            :specifications,
            :features,
            :source_api
        ) RETURNING id INTO :id
    """

    # Sanitise before binding
    if isinstance(pricing_data.get('specifications'), (dict, list)):
        pricing_data['specifications'] = _dumps(pricing_data['specifications'])
    if isinstance(pricing_data.get('features'), (dict, list)):
        pricing_data['features'] = _dumps(pricing_data['features'])
    if pricing_data.get('price_per_hour') is None:
        pricing_data['price_per_hour'] = 0.0
    if pricing_data.get('price_per_month') is None:
        pricing_data['price_per_month'] = 0.0

    with db.get_connection() as conn:
        cursor = conn.cursor()
        id_var = cursor.var(int)
        pricing_data['id'] = id_var

        cursor.execute(query, pricing_data)
        conn.commit()

        return id_var.getvalue()[0]


def bulk_insert_pricing_data(pricing_list: List[Dict]) -> int:
    """
    Bulk insert pricing data for better performance

    Args:
        pricing_list: List of pricing dictionaries

    Returns:
        int: Number of rows inserted
    """
    query = """
        INSERT INTO pricing_cache (
            cloud_provider, service_category, service_name, instance_type,
            metric, region, price_per_hour, price_per_month, currency,
            specifications, features, source_api
        ) VALUES (
            :cloud_provider, :service_category, :service_name, :instance_type,
            :metric, :region, :price_per_hour, :price_per_month, :currency,
            :specifications, :features, :source_api
        )
    """

    # Keys that map to bind placeholders in the INSERT above.
    # python-oracledb raises DPY-4008 if a dict contains extra keys with no
    # matching placeholder, so we strip anything not in this set.
    _ALLOWED = {
        'cloud_provider', 'service_category', 'service_name', 'instance_type',
        'metric', 'region', 'price_per_hour', 'price_per_month', 'currency',
        'specifications', 'features', 'source_api',
    }

    # Sanitise every row before binding:
    #   - strip extra keys (e.g. 'pricing_model') that have no placeholder
    #   - specifications / features must be JSON strings
    #   - price_per_hour / price_per_month must not be None
    sanitised = []
    for item in pricing_list:
        row = {k: v for k, v in item.items() if k in _ALLOWED}
        if isinstance(row.get('specifications'), (dict, list)):
            row['specifications'] = _dumps(row['specifications'])
        if isinstance(row.get('features'), (dict, list)):
            row['features'] = _dumps(row['features'])
        if row.get('price_per_hour') is None:
            row['price_per_hour'] = 0.0
        if row.get('price_per_month') is None:
            row['price_per_month'] = 0.0
        if 'metric' not in row:
            row['metric'] = None
        # Truncate string columns to their DB column limits
        if row.get('instance_type') and len(row['instance_type']) > 100:
            row['instance_type'] = row['instance_type'][:100]
        if row.get('service_name') and len(row['service_name']) > 200:
            row['service_name'] = row['service_name'][:200]
        if row.get('metric') and len(row['metric']) > 200:
            row['metric'] = row['metric'][:200]
        sanitised.append(row)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, sanitised)
        conn.commit()
        return cursor.rowcount


def get_pricing_by_service(
    service_category: str,
    region: Optional[str] = None,
    cloud_provider: Optional[str] = None,
    billing_type: Optional[str] = None,
) -> List[Dict]:
    """
    Retrieve pricing data for a specific service category.

    Args:
        service_category: Database, Compute, or Storage
        region: Optional region filter
        cloud_provider: Optional provider filter
        billing_type: Optional billing-type category filter (instance_type column)
                      e.g. "Compute", "Storage", "Network", "API/Request"

    Returns:
        List of pricing records
    """
    query = """
        SELECT
            id, cloud_provider, service_category, service_name,
            instance_type, metric, region, price_per_hour, price_per_month,
            currency,
            DBMS_LOB.SUBSTR(specifications, 4000, 1) as specifications,
            DBMS_LOB.SUBSTR(features, 4000, 1) as features,
            last_updated
        FROM pricing_cache
        WHERE service_category = :service_category
    """

    params = {'service_category': service_category}

    if region:
        query += " AND region = :region"
        params['region'] = region

    if cloud_provider:
        query += " AND cloud_provider = :cloud_provider"
        params['cloud_provider'] = cloud_provider

    if billing_type:
        query += " AND instance_type = :billing_type"
        params['billing_type'] = billing_type

    query += " ORDER BY price_per_month ASC"

    results = db.execute_query(query, params)

    # Convert to list of dictionaries
    columns = [
        'id', 'cloud_provider', 'service_category', 'service_name',
        'instance_type', 'metric', 'region', 'price_per_hour', 'price_per_month',
        'currency', 'specifications', 'features', 'last_updated'
    ]

    # Convert results and handle potential None values
    result_list = []
    for row in results:
        row_dict = dict(zip(columns, row))
        # Parse specifications JSON string if present
        if row_dict.get('specifications'):
            try:
                row_dict['specifications'] = json.loads(row_dict['specifications'])
            except:
                row_dict['specifications'] = {}
        else:
            row_dict['specifications'] = {}
        result_list.append(row_dict)

    return result_list


def delete_old_pricing(cloud_provider: str, service_category: str) -> int:
    """
    Delete old pricing data before refresh

    Args:
        cloud_provider: Provider to delete data for
        service_category: Category to delete

    Returns:
        int: Number of rows deleted
    """
    query = """
        DELETE FROM pricing_cache
        WHERE cloud_provider = :cloud_provider
        AND service_category = :service_category
    """

    return db.execute_dml(query, {
        'cloud_provider': cloud_provider,
        'service_category': service_category
    })


def check_pricing_freshness() -> Dict[str, datetime]:
    """
    Check when pricing data was last updated for each provider

    Returns:
        Dict mapping provider to last update timestamp
    """
    query = """
        SELECT cloud_provider, MAX(last_updated) as last_update
        FROM pricing_cache
        GROUP BY cloud_provider
    """

    results = db.execute_query(query)
    return {row[0]: row[1] for row in results}


# ============================================
# PRICING HISTORY QUERIES
# ============================================

def archive_pricing_to_history() -> int:
    """
    Archive current pricing data to history table

    Returns:
        int: Number of rows archived
    """
    query = """
        INSERT INTO pricing_cache_history (
            pricing_cache_id, cloud_provider, service_category,
            service_name, instance_type, region, price_per_hour,
            price_per_month, currency, specifications
        )
        SELECT
            id, cloud_provider, service_category, service_name,
            instance_type, region, price_per_hour, price_per_month,
            currency, specifications
        FROM pricing_cache
    """

    return db.execute_dml(query)


def get_price_history(
    cloud_provider: str,
    service_name: str,
    days: int = 30
) -> List[Dict]:
    """
    Get price history for a specific service

    Args:
        cloud_provider: Cloud provider
        service_name: Service name
        days: Number of days of history

    Returns:
        List of historical pricing records
    """
    query = """
        SELECT
            recorded_at,
            price_per_month,
            price_change_pct
        FROM pricing_cache_history
        WHERE cloud_provider = :cloud_provider
        AND service_name = :service_name
        AND recorded_at >= SYSDATE - :days
        ORDER BY recorded_at DESC
    """

    results = db.execute_query(query, {
        'cloud_provider': cloud_provider,
        'service_name': service_name,
        'days': days
    })

    return [
        {
            'recorded_at': row[0],
            'price_per_month': float(row[1]) if row[1] else None,
            'price_change_pct': float(row[2]) if row[2] else None
        }
        for row in results
    ]


# ============================================
# SERVICE MAPPINGS QUERIES
# ============================================

def get_service_mapping(category: str, service_name: str, provider: str) -> Optional[Dict]:
    """
    Get cross-cloud service mappings

    Args:
        category: Service category
        service_name: Service name
        provider: Source provider (aws, azure, gcp, oci)

    Returns:
        Dict with equivalent services across clouds
    """
    provider_col = f"{provider.lower()}_service"

    query = f"""
        SELECT
            aws_service, azure_service, gcp_service, oci_service,
            description, confidence_score, mapping_type
        FROM service_mappings
        WHERE category = :category
        AND UPPER({provider_col}) = UPPER(:service_name)
    """

    results = db.execute_query(query, {
        'category': category,
        'service_name': service_name
    })

    if not results:
        return None

    row = results[0]
    return {
        'aws': row[0],
        'azure': row[1],
        'gcp': row[2],
        'oci': row[3],
        'description': row[4],
        'confidence_score': float(row[5]) if row[5] else 0.0,
        'mapping_type': row[6]
    }


def insert_service_mapping(mapping: Dict) -> int:
    """
    Insert a new service mapping

    Args:
        mapping: Dictionary containing mapping information

    Returns:
        int: ID of inserted mapping
    """
    query = """
        INSERT INTO service_mappings (
            aws_service, azure_service, gcp_service, oci_service,
            category, description, confidence_score, mapping_type, notes
        ) VALUES (
            :aws_service, :azure_service, :gcp_service, :oci_service,
            :category, :description, :confidence_score, :mapping_type, :notes
        ) RETURNING id INTO :id
    """

    with db.get_connection() as conn:
        cursor = conn.cursor()
        id_var = cursor.var(int)
        mapping['id'] = id_var

        cursor.execute(query, mapping)
        conn.commit()

        return id_var.getvalue()[0]


# ============================================
# VECTOR SEARCH QUERIES
# ============================================

def insert_document(doc_name: str, doc_source: str, content: str, doc_type: str = 'PDF') -> int:
    """
    Insert a document into oci_pricing_docs

    Args:
        doc_name: Document name
        doc_source: Source URL or path
        content: Document content
        doc_type: Document type (PDF, HTML, TXT)

    Returns:
        int: Document ID
    """
    query = """
        INSERT INTO oci_pricing_docs (
            document_name, document_source, document_type, content,
            metadata, last_processed
        ) VALUES (
            :doc_name, :doc_source, :doc_type, :content,
            :metadata, CURRENT_TIMESTAMP
        ) RETURNING id INTO :id
    """

    metadata = _dumps({
        'uploaded_at': datetime.now().isoformat(),
        'doc_type': doc_type
    })

    with db.get_connection() as conn:
        cursor = conn.cursor()
        id_var = cursor.var(int)

        cursor.execute(query, {
            'doc_name': doc_name,
            'doc_source': doc_source,
            'doc_type': doc_type,
            'content': content,
            'metadata': metadata,
            'id': id_var
        })
        conn.commit()

        return id_var.getvalue()[0]


def insert_chunks_with_embeddings(doc_id: int, chunks: List[Tuple[int, str, str]]) -> int:
    """
    Insert document chunks with embeddings using Oracle's vector embedding

    Args:
        doc_id: Document ID
        chunks: List of tuples (chunk_id, chunk_text, embedding_vector_json)

    Returns:
        int: Number of chunks inserted
    """
    # This will be called after chunks are created by the document processor
    # The embedding will be generated using Oracle's VECTOR_EMBEDDING function

    query = """
        INSERT INTO doc_chunks (doc_id, chunk_id, chunk_text, chunk_vector, chunk_metadata)
        SELECT
            :doc_id,
            t.chunk_id,
            t.chunk_text,
            TO_VECTOR(t.embed_vector),
            JSON_OBJECT('chunk_id' VALUE t.chunk_id, 'length' VALUE LENGTH(t.chunk_text))
        FROM JSON_TABLE(
            :chunks_json,
            '$[*]' COLUMNS (
                chunk_id NUMBER PATH '$.chunk_id',
                chunk_text VARCHAR2(4000) PATH '$.chunk_text',
                embed_vector CLOB PATH '$.embed_vector'
            )
        ) t
    """

    chunks_json = _dumps([
        {
            'chunk_id': chunk_id,
            'chunk_text': text[:4000],  # Limit for VARCHAR2
            'embed_vector': vector_json
        }
        for chunk_id, text, vector_json in chunks
    ])

    return db.execute_dml(query, {
        'doc_id': doc_id,
        'chunks_json': chunks_json
    })


def vector_search(query_text: str, top_k: int = 5) -> List[Dict]:
    """
    Perform vector similarity search for relevant document chunks

    Args:
        query_text: Query text to search for
        top_k: Number of top results to return

    Returns:
        List of relevant chunks with similarity scores
    """
    query = """
        SELECT
            dc.chunk_text,
            oci.document_name,
            oci.document_source,
            VECTOR_DISTANCE(dc.chunk_vector, VECTOR_EMBEDDING(TEXT_EMBED_MODEL USING :query_text AS data), COSINE) as distance
        FROM doc_chunks dc
        JOIN oci_pricing_docs oci ON dc.doc_id = oci.id
        ORDER BY distance ASC
        FETCH FIRST :top_k ROWS ONLY
    """

    results = db.execute_query(query, {
        'query_text': query_text,
        'top_k': top_k
    })

    return [
        {
            'chunk_text': row[0],
            'document_name': row[1],
            'document_source': row[2],
            'similarity_score': 1 - float(row[3])  # Convert distance to similarity
        }
        for row in results
    ]


# ============================================
# AGENT LOGGING QUERIES
# ============================================

def log_agent_execution(
    agent_name: str,
    agent_type: str,
    input_data: Dict,
    output_data: Dict,
    context: Dict,
    decision_reasoning: str,
    execution_time_ms: int,
    status: str = 'SUCCESS',
    error_message: Optional[str] = None,
    api_calls_made: int = 0,
    tokens_used: int = 0
) -> int:
    """
    Log agent execution details

    Args:
        agent_name: Name of the agent
        agent_type: Type of agent (mapping, pricing, comparison)
        input_data: Input data dictionary
        output_data: Output data dictionary
        context: Context dictionary
        decision_reasoning: Explanation of agent's decision
        execution_time_ms: Execution time in milliseconds
        status: SUCCESS, FAILURE, PARTIAL, TIMEOUT
        error_message: Error message if failed
        api_calls_made: Number of API calls made
        tokens_used: Number of LLM tokens used

    Returns:
        int: Log entry ID
    """
    query = """
        INSERT INTO log_agents (
            agent_name, agent_type, input_data, output_data, context,
            decision_reasoning, execution_time_ms, status, error_message,
            api_calls_made, tokens_used
        ) VALUES (
            :agent_name, :agent_type, :input_data, :output_data, :context,
            :decision_reasoning, :execution_time_ms, :status, :error_message,
            :api_calls_made, :tokens_used
        ) RETURNING id INTO :id
    """

    with db.get_connection() as conn:
        cursor = conn.cursor()
        id_var = cursor.var(int)

        cursor.execute(query, {
            'agent_name': agent_name,
            'agent_type': agent_type,
            'input_data': _dumps(input_data),
            'output_data': _dumps(output_data),
            'context': _dumps(context),
            'decision_reasoning': decision_reasoning,
            'execution_time_ms': execution_time_ms,
            'status': status,
            'error_message': error_message,
            'api_calls_made': api_calls_made,
            'tokens_used': tokens_used,
            'id': id_var
        })
        conn.commit()

        return id_var.getvalue()[0]


def get_agent_logs(
    agent_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict]:
    """
    Retrieve agent execution logs

    Args:
        agent_name: Optional filter by agent name
        status: Optional filter by status
        limit: Maximum number of logs to return

    Returns:
        List of log entries
    """
    query = """
        SELECT
            id, agent_name, agent_type, execution_timestamp,
            input_data, output_data, decision_reasoning,
            execution_time_ms, status, api_calls_made, tokens_used
        FROM log_agents
        WHERE 1=1
    """

    params = {}

    if agent_name:
        query += " AND agent_name = :agent_name"
        params['agent_name'] = agent_name

    if status:
        query += " AND status = :status"
        params['status'] = status

    query += " ORDER BY execution_timestamp DESC FETCH FIRST :limit ROWS ONLY"
    params['limit'] = limit

    results = db.execute_query(query, params)

    columns = [
        'id', 'agent_name', 'agent_type', 'execution_timestamp',
        'input_data', 'output_data', 'decision_reasoning',
        'execution_time_ms', 'status', 'api_calls_made', 'tokens_used'
    ]

    return [dict(zip(columns, row)) for row in results]
