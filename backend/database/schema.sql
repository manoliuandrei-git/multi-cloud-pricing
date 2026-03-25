-- ============================================
-- Multi-Cloud Pricing Calculator Database Schema
-- Oracle ATP (23ai) with Vector Search Support
-- ============================================

-- ============================================
-- 1. PRICING CACHE TABLE
-- Stores current pricing data from all cloud providers
-- ============================================
CREATE TABLE pricing_cache (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    cloud_provider VARCHAR2(50) NOT NULL,
    service_category VARCHAR2(100) NOT NULL,
    service_name VARCHAR2(200) NOT NULL,
    instance_type VARCHAR2(100),         -- billing-type category: Compute, Storage, Network, etc.
    metric VARCHAR2(200),                -- raw billing metric: "Per OCPU Per Hour", "1 Hour", etc.
    region VARCHAR2(50) NOT NULL,
    price_per_hour NUMBER(10,4),
    price_per_month NUMBER(10,2),
    currency VARCHAR2(10) DEFAULT 'USD',
    specifications CLOB CHECK (specifications IS JSON),
    features CLOB,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_api VARCHAR2(100),
    PRIMARY KEY (id),
    CONSTRAINT chk_provider CHECK (cloud_provider IN ('AWS', 'Azure', 'GCP', 'OCI'))
);

-- Indexes for faster queries
CREATE INDEX idx_pricing_provider ON pricing_cache(cloud_provider);
CREATE INDEX idx_pricing_category ON pricing_cache(service_category);
CREATE INDEX idx_pricing_region ON pricing_cache(region);
CREATE INDEX idx_pricing_service ON pricing_cache(service_name);
CREATE INDEX idx_pricing_updated ON pricing_cache(last_updated);


-- ============================================
-- 2. PRICING HISTORY TABLE
-- Stores historical pricing data for trend analysis
-- ============================================
CREATE TABLE pricing_cache_history (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    pricing_cache_id NUMBER,
    cloud_provider VARCHAR2(50) NOT NULL,
    service_category VARCHAR2(100) NOT NULL,
    service_name VARCHAR2(200) NOT NULL,
    instance_type VARCHAR2(100),
    region VARCHAR2(50) NOT NULL,
    price_per_hour NUMBER(10,4),
    price_per_month NUMBER(10,2),
    currency VARCHAR2(10) DEFAULT 'USD',
    specifications CLOB CHECK (specifications IS JSON),
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price_change_pct NUMBER(5,2),
    PRIMARY KEY (id)
);

-- Indexes for historical queries
CREATE INDEX idx_history_provider ON pricing_cache_history(cloud_provider);
CREATE INDEX idx_history_service ON pricing_cache_history(service_name);
CREATE INDEX idx_history_recorded ON pricing_cache_history(recorded_at);


-- ============================================
-- 3. SERVICE MAPPINGS TABLE
-- Cross-cloud service equivalency mappings
-- ============================================
CREATE TABLE service_mappings (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    aws_service VARCHAR2(200),
    azure_service VARCHAR2(200),
    gcp_service VARCHAR2(200),
    oci_service VARCHAR2(200),
    category VARCHAR2(100) NOT NULL,
    description VARCHAR2(500),
    confidence_score NUMBER(3,2),
    mapping_type VARCHAR2(50) DEFAULT 'exact',
    notes CLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT chk_confidence CHECK (confidence_score BETWEEN 0 AND 1),
    CONSTRAINT chk_mapping_type CHECK (mapping_type IN ('exact', 'approximate', 'alternative'))
);

-- Index for mapping queries
CREATE INDEX idx_mapping_category ON service_mappings(category);
CREATE INDEX idx_mapping_aws ON service_mappings(aws_service);
CREATE INDEX idx_mapping_azure ON service_mappings(azure_service);
CREATE INDEX idx_mapping_gcp ON service_mappings(gcp_service);
CREATE INDEX idx_mapping_oci ON service_mappings(oci_service);


-- ============================================
-- 4. OCI PRICING DOCUMENTS TABLE
-- Stores OCI pricing documentation for vector search
-- ============================================
CREATE TABLE oci_pricing_docs (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    document_name VARCHAR2(500) NOT NULL,
    document_source VARCHAR2(1000),
    document_type VARCHAR2(50),
    content CLOB,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_processed TIMESTAMP,
    metadata CLOB CHECK (metadata IS JSON),
    PRIMARY KEY (id)
);

-- Index for document queries
CREATE INDEX idx_docs_name ON oci_pricing_docs(document_name);
CREATE INDEX idx_docs_type ON oci_pricing_docs(document_type);
CREATE INDEX idx_docs_processed ON oci_pricing_docs(last_processed);


-- ============================================
-- 5. DOCUMENT CHUNKS WITH EMBEDDINGS TABLE
-- Stores chunked documents with vector embeddings for RAG
-- ============================================
CREATE TABLE doc_chunks (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    doc_id NUMBER NOT NULL,
    chunk_id NUMBER NOT NULL,
    chunk_text CLOB NOT NULL,
    chunk_vector VECTOR(384, FLOAT32),
    chunk_metadata CLOB CHECK (chunk_metadata IS JSON),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (doc_id) REFERENCES oci_pricing_docs(id) ON DELETE CASCADE
);

-- Vector index for similarity search
CREATE VECTOR INDEX idx_chunk_vector ON doc_chunks(chunk_vector)
ORGANIZATION NEIGHBOR PARTITIONS
WITH DISTANCE COSINE
WITH TARGET ACCURACY 95;

-- Regular indexes
CREATE INDEX idx_chunks_doc ON doc_chunks(doc_id);
CREATE INDEX idx_chunks_created ON doc_chunks(created_at);


-- ============================================
-- 6. AGENT LOGGING TABLE
-- Stores agent execution logs, decisions, and context
-- ============================================
CREATE TABLE log_agents (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    agent_name VARCHAR2(100) NOT NULL,
    agent_type VARCHAR2(50) NOT NULL,
    execution_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    input_data CLOB CHECK (input_data IS JSON),
    output_data CLOB CHECK (output_data IS JSON),
    context CLOB CHECK (context IS JSON),
    decision_reasoning CLOB,
    execution_time_ms NUMBER,
    status VARCHAR2(50) DEFAULT 'SUCCESS',
    error_message CLOB,
    api_calls_made NUMBER DEFAULT 0,
    tokens_used NUMBER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT chk_status CHECK (status IN ('SUCCESS', 'FAILURE', 'PARTIAL', 'TIMEOUT'))
);

-- Indexes for agent log queries
CREATE INDEX idx_log_agent_name ON log_agents(agent_name);
CREATE INDEX idx_log_timestamp ON log_agents(execution_timestamp);
CREATE INDEX idx_log_status ON log_agents(status);


-- ============================================
-- 7. USER SELECTIONS TABLE (for future use)
-- Stores user-selected service combinations
-- ============================================
CREATE TABLE user_selections (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    session_id VARCHAR2(100) NOT NULL,
    pricing_cache_id NUMBER NOT NULL,
    selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes VARCHAR2(500),
    PRIMARY KEY (id),
    FOREIGN KEY (pricing_cache_id) REFERENCES pricing_cache(id)
);

-- Index for session queries
CREATE INDEX idx_selection_session ON user_selections(session_id);


-- ============================================
-- HELPER VIEWS
-- ============================================

-- View for latest pricing per service
CREATE OR REPLACE VIEW v_latest_pricing AS
SELECT
    cloud_provider,
    service_category,
    service_name,
    instance_type,
    region,
    price_per_hour,
    price_per_month,
    currency,
    specifications,
    last_updated
FROM (
    SELECT
        pc.*,
        ROW_NUMBER() OVER (
            PARTITION BY cloud_provider, service_category, service_name, instance_type, region
            ORDER BY last_updated DESC
        ) as rn
    FROM pricing_cache pc
)
WHERE rn = 1;


-- View for price comparison across providers
CREATE OR REPLACE VIEW v_price_comparison AS
SELECT
    service_category,
    service_name,
    region,
    MAX(CASE WHEN cloud_provider = 'AWS' THEN price_per_month END) as aws_price,
    MAX(CASE WHEN cloud_provider = 'Azure' THEN price_per_month END) as azure_price,
    MAX(CASE WHEN cloud_provider = 'GCP' THEN price_per_month END) as gcp_price,
    MAX(CASE WHEN cloud_provider = 'OCI' THEN price_per_month END) as oci_price
FROM v_latest_pricing
GROUP BY service_category, service_name, region;


-- ============================================
-- HELPER PROCEDURES
-- ============================================

-- Procedure to archive pricing to history
CREATE OR REPLACE PROCEDURE sp_archive_pricing_to_history AS
BEGIN
    INSERT INTO pricing_cache_history (
        pricing_cache_id,
        cloud_provider,
        service_category,
        service_name,
        instance_type,
        region,
        price_per_hour,
        price_per_month,
        currency,
        specifications,
        recorded_at
    )
    SELECT
        id,
        cloud_provider,
        service_category,
        service_name,
        instance_type,
        region,
        price_per_hour,
        price_per_month,
        currency,
        specifications,
        CURRENT_TIMESTAMP
    FROM pricing_cache;

    COMMIT;

    DBMS_OUTPUT.PUT_LINE('Archived ' || SQL%ROWCOUNT || ' pricing records to history');
END;
/


-- Procedure to cleanup old logs (keep last 90 days)
CREATE OR REPLACE PROCEDURE sp_cleanup_old_logs AS
BEGIN
    DELETE FROM log_agents
    WHERE execution_timestamp < SYSDATE - 90;

    COMMIT;

    DBMS_OUTPUT.PUT_LINE('Deleted ' || SQL%ROWCOUNT || ' old log records');
END;
/


-- ============================================
-- INITIAL DATA SEED (Service Categories)
-- ============================================

-- Insert some common service mappings
INSERT INTO service_mappings (category, aws_service, azure_service, gcp_service, oci_service, confidence_score, mapping_type, description)
VALUES ('Database', 'RDS MySQL', 'Azure Database for MySQL', 'Cloud SQL MySQL', 'MySQL Database Service', 0.95, 'exact', 'Managed MySQL database service');

INSERT INTO service_mappings (category, aws_service, azure_service, gcp_service, oci_service, confidence_score, mapping_type, description)
VALUES ('Database', 'RDS PostgreSQL', 'Azure Database for PostgreSQL', 'Cloud SQL PostgreSQL', 'PostgreSQL Database Service', 0.95, 'exact', 'Managed PostgreSQL database service');

INSERT INTO service_mappings (category, aws_service, azure_service, gcp_service, oci_service, confidence_score, mapping_type, description)
VALUES ('Compute', 'EC2', 'Virtual Machines', 'Compute Engine', 'Compute', 0.90, 'exact', 'Virtual machine instances');

INSERT INTO service_mappings (category, aws_service, azure_service, gcp_service, oci_service, confidence_score, mapping_type, description)
VALUES ('Storage', 'S3', 'Blob Storage', 'Cloud Storage', 'Object Storage', 0.95, 'exact', 'Object storage service');

COMMIT;

-- ============================================
-- END OF SCHEMA
-- ============================================
