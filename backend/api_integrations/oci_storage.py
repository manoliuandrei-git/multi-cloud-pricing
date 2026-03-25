"""
OCI Object Storage Integration
Fetches OCI pricing documents from Object Storage and processes them for RAG.

Processing pipeline (Oracle-native, primary):
  DBMS_CLOUD.GET_OBJECT (inline SQL subquery)
    → DBMS_VECTOR_CHAIN.UTL_TO_TEXT  (BLOB → CLOB)
    → DBMS_VECTOR_CHAIN.UTL_TO_CHUNKS (CLOB → VECTOR_ARRAY_T)
    → DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDINGS (VECTOR_ARRAY_T → VECTOR_ARRAY_T)
    → INSERT INTO doc_chunks

Key notes vs. the original broken PL/SQL approach:
  • The whole pipeline runs as a single SQL INSERT…SELECT statement — no
    PL/SQL CLOB variable is passed into the chain.  Oracle's DBMS_VECTOR_CHAIN
    functions work in SQL context when data originates from a table column or
    inline subquery, but fail with PLS-00306 when fed a PL/SQL variable.
  • json_table uses '$[*]' (array iterator) not '$' (root object).
  • DBMS_CLOUD.GET_OBJECT is called as a scalar SQL expression in a FROM
    subquery (SELECT … FROM DUAL) — not as a PL/SQL OUT-parameter bind —
    which avoids ORA-06502.

Python/PyPDF2 fallback is retained in case DBMS_VECTOR_CHAIN privileges
are not available on this ATP account.

Authentication uses the DBMS_CLOUD credential configured in ATP
(OCI_CREDENTIAL_NAME in .env, defaults to 'OBJ_STORE_CRED').
"""
import os
import json
import tempfile
from typing import List, Dict, Optional

from database.connection import db
from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class OCIStorageClient:
    """Client for OCI Object Storage using ATP DBMS_CLOUD"""

    def __init__(self):
        self.bucket_name    = config.OCI_BUCKET_NAME
        self.namespace      = config.OCI_NAMESPACE
        self.credential_name = config.OCI_CREDENTIAL_NAME
        self.region         = config.OCI_REGION

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _base_uri(self) -> str:
        return (
            f'https://objectstorage.{self.region}.oraclecloud.com'
            f'/n/{self.namespace}/b/{self.bucket_name}/o/'
        )

    def _object_uri(self, object_name: str) -> str:
        return f'{self._base_uri()}{object_name}'

    # ------------------------------------------------------------------ #
    # List documents                                                       #
    # ------------------------------------------------------------------ #

    def list_documents(
        self,
        prefix: str = '',
        file_extension: str = '.pdf'
    ) -> List[str]:
        """
        List documents in the OCI bucket using DBMS_CLOUD.LIST_OBJECTS.

        DBMS_CLOUD table-function arguments cannot use SQL bind variables,
        so credential_name and location_uri are embedded from config
        (they are never user-supplied).
        """
        try:
            location_uri = self._base_uri()
            pattern = (
                f'{prefix}%{file_extension}' if prefix
                else f'%{file_extension}'
            )

            query = f"""
                SELECT t.object_name
                FROM TABLE(
                    DBMS_CLOUD.LIST_OBJECTS(
                        '{self.credential_name}',
                        '{location_uri}'
                    )
                ) t
                WHERE UPPER(t.object_name) LIKE UPPER(:pattern)
            """

            results = db.execute_query(query, {'pattern': pattern})
            object_names = [row[0] for row in results]
            logger.info(
                f"Found {len(object_names)} document(s) in "
                f"bucket '{self.bucket_name}'"
            )
            return object_names

        except Exception as e:
            logger.error(f"Failed to list documents from OCI bucket: {e}")
            raise

    # ------------------------------------------------------------------ #
    # Strategy 1 — Oracle-native SQL pipeline                             #
    # ------------------------------------------------------------------ #

    def _process_document_oracle_native(
        self, object_name: str, doc_id: int
    ) -> int:
        """
        Process a PDF entirely inside Oracle 23ai with a single SQL statement.

        The pipeline runs as pure SQL — no PL/SQL CLOB variable is involved:

            (SELECT DBMS_CLOUD.GET_OBJECT(...) AS pdf_blob FROM DUAL)  -- BLOB
              → DBMS_VECTOR_CHAIN.UTL_TO_TEXT(src.pdf_blob)            -- CLOB
              → DBMS_VECTOR_CHAIN.UTL_TO_CHUNKS(text, chunk_params)    -- VECTOR_ARRAY_T
              → DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDINGS(chunks, model)     -- VECTOR_ARRAY_T
              → JSON_TABLE(t.column_value, '$[*]' ...)                  -- rows
              → INSERT INTO doc_chunks

        The '$[*]' path in JSON_TABLE is required to iterate over the array
        returned by UTL_TO_EMBEDDINGS (not '$' which addresses only the root).

        Returns:
            Number of chunks inserted
        """
        object_uri   = self._object_uri(object_name)
        embed_model  = config.EMBEDDING_MODEL   # e.g. DOC_MODEL — no quotes needed in JSON

        # Chunk parameters — mirroring the Oracle documentation example
        chunk_params = '{"max":"200","overlap":"20","language":"american","normalize":"all"}'
        embed_params = f'{{"provider":"database","model":"{embed_model}"}}'

        # credential_name comes from config, embed_model from config — safe to inline
        insert_sql = f"""
            INSERT INTO doc_chunks
                (doc_id, chunk_id, chunk_text, chunk_vector, chunk_metadata)
            SELECT
                :doc_id,
                et.embed_id,
                et.embed_data,
                TO_VECTOR(et.embed_vector),
                JSON_OBJECT('chunk_id' VALUE et.embed_id, 'source' VALUE :obj_name)
            FROM
                (SELECT DBMS_CLOUD.GET_OBJECT(
                            '{self.credential_name}', :object_uri
                        ) AS pdf_blob
                 FROM DUAL) src,
                DBMS_VECTOR_CHAIN.UTL_TO_EMBEDDINGS(
                    DBMS_VECTOR_CHAIN.UTL_TO_CHUNKS(
                        DBMS_VECTOR_CHAIN.UTL_TO_TEXT(src.pdf_blob),
                        JSON('{chunk_params}')
                    ),
                    JSON('{embed_params}')
                ) t,
                JSON_TABLE(t.column_value, '$[*]' COLUMNS (
                    embed_id     NUMBER         PATH '$.embed_id',
                    embed_data   VARCHAR2(4000) PATH '$.embed_data',
                    embed_vector CLOB           PATH '$.embed_vector'
                )) et
        """

        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Clear any existing chunks first
            cursor.execute(
                "DELETE FROM doc_chunks WHERE doc_id = :id",
                {'id': doc_id}
            )

            # Run the pipeline
            cursor.execute(insert_sql, {
                'doc_id':     doc_id,
                'obj_name':   object_name,
                'object_uri': object_uri
            })
            chunk_count = cursor.rowcount

            # Mark document as processed
            cursor.execute(
                """UPDATE oci_pricing_docs
                   SET    last_processed = CURRENT_TIMESTAMP
                   WHERE  id = :id""",
                {'id': doc_id}
            )

            conn.commit()

        logger.info(
            f"Oracle-native pipeline: {chunk_count} chunks for '{object_name}'"
        )
        return chunk_count

    # ------------------------------------------------------------------ #
    # Strategy 2 — Python / PyPDF2 fallback                               #
    # ------------------------------------------------------------------ #

    def _process_document_python_fallback(
        self, object_name: str, doc_id: int
    ) -> int:
        """
        Fallback: download BLOB via SQL SELECT, extract text with PyPDF2,
        store chunks with per-row VECTOR_EMBEDDING SQL inserts.

        Used when DBMS_VECTOR_CHAIN is unavailable on this ATP account.

        The BLOB is retrieved with:
            SELECT DBMS_CLOUD.GET_OBJECT(:cred, :uri) FROM DUAL
        This is a SQL function-call expression (not a PL/SQL OUT bind) so
        python-oracledb returns a LOB locator that can be read immediately.

        Returns:
            Number of chunks inserted
        """
        from utils.document_processor import DocumentProcessor
        from utils.vector_utils import store_chunks_with_embeddings

        object_uri = self._object_uri(object_name)
        logger.info(f"Python fallback: downloading '{object_name}'...")

        # Download BLOB via SQL SELECT
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DBMS_CLOUD.GET_OBJECT(:cred_name, :object_uri) FROM DUAL",
                {'cred_name': self.credential_name, 'object_uri': object_uri}
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                raise ValueError(
                    f"DBMS_CLOUD.GET_OBJECT returned nothing for '{object_name}'. "
                    "Verify the credential and object name."
                )
            blob_bytes = row[0].read()   # LOB locator → bytes

        logger.info(f"Downloaded {len(blob_bytes):,} bytes for '{object_name}'")

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(blob_bytes)
                tmp_path = tmp.name

            # Extract text and create chunks
            doc_processor = DocumentProcessor(chunk_size=1000, chunk_overlap=200)
            full_text, chunks = doc_processor.process_document(
                tmp_path,
                document_name=object_name,
                document_type='PDF'
            )
            logger.info(
                f"Extracted {len(full_text):,} chars, {len(chunks)} chunks "
                f"from '{object_name}'"
            )

            with db.get_connection() as conn:
                cursor = conn.cursor()

                # Persist extracted text
                cursor.execute(
                    """UPDATE oci_pricing_docs
                       SET    content        = :content,
                              last_processed = CURRENT_TIMESTAMP
                       WHERE  id = :doc_id""",
                    {'content': full_text[:32767], 'doc_id': doc_id}
                )

                # Clear old chunks
                cursor.execute(
                    "DELETE FROM doc_chunks WHERE doc_id = :doc_id",
                    {'doc_id': doc_id}
                )
                conn.commit()

            # Embed and insert chunks using VECTOR_EMBEDDING per row
            chunk_count = store_chunks_with_embeddings(doc_id, chunks)
            logger.info(
                f"Python fallback: {chunk_count} chunks stored for '{object_name}'"
            )
            return chunk_count

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    def process_and_store_documents(
        self, force_refresh: bool = False
    ) -> Dict:
        """
        List all PDFs in the bucket, process each one, and store chunks
        with vector embeddings in the database ready for RAG queries.

        Tries the Oracle-native SQL pipeline first.  If DBMS_VECTOR_CHAIN is
        unavailable (privilege not granted), automatically falls back to the
        Python + PyPDF2 pipeline.

        Already-processed documents are skipped unless force_refresh=True.
        """
        stats: Dict = {
            'documents_found':     0,
            'documents_processed': 0,
            'documents_skipped':   0,
            'chunks_created':      0,
            'errors':              []
        }

        try:
            object_names = self.list_documents(file_extension='.pdf')
            stats['documents_found'] = len(object_names)

            if not object_names:
                logger.warning(
                    f"No PDF documents found in bucket '{self.bucket_name}'. "
                    "Upload your OCI pricing PDFs and make sure the credential "
                    f"'{self.credential_name}' is configured in ATP."
                )
                return stats

            for object_name in object_names:
                try:
                    # Skip if already ingested
                    if not force_refresh:
                        check = db.execute_query(
                            """SELECT COUNT(*) FROM oci_pricing_docs
                               WHERE document_name  = :name
                               AND   last_processed IS NOT NULL""",
                            {'name': object_name}
                        )
                        if check and check[0][0] > 0:
                            logger.info(f"Already ingested, skipping: '{object_name}'")
                            stats['documents_skipped'] += 1
                            continue

                    logger.info(f"Processing: '{object_name}'")

                    # Get or create doc record
                    from database.queries import insert_document

                    existing = db.execute_query(
                        "SELECT id FROM oci_pricing_docs WHERE document_name = :name",
                        {'name': object_name}
                    )
                    if existing:
                        doc_id = existing[0][0]
                        if force_refresh:
                            db.execute_dml(
                                "UPDATE oci_pricing_docs "
                                "SET last_processed = NULL WHERE id = :id",
                                {'id': doc_id}
                            )
                    else:
                        doc_id = insert_document(
                            doc_name=object_name,
                            doc_source=self._object_uri(object_name),
                            content='',
                            doc_type='PDF'
                        )

                    # Try Oracle-native SQL pipeline first
                    chunk_count = 0
                    try:
                        chunk_count = self._process_document_oracle_native(
                            object_name, doc_id
                        )
                    except Exception as native_err:
                        logger.warning(
                            f"Oracle-native pipeline failed "
                            f"({type(native_err).__name__}: {native_err}). "
                            "Falling back to Python/PyPDF2..."
                        )
                        chunk_count = self._process_document_python_fallback(
                            object_name, doc_id
                        )

                    stats['documents_processed'] += 1
                    stats['chunks_created'] += chunk_count

                except Exception as e:
                    error_msg = f"Failed to process '{object_name}': {e}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
                    continue

            logger.info(f"OCI document ingestion complete: {stats}")

        except Exception as e:
            error_msg = f"OCI document ingestion aborted: {e}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

        return stats


    # ------------------------------------------------------------------ #
    # Direct bulk pricing extraction (bypasses RAG)                      #
    # ------------------------------------------------------------------ #

    def extract_all_pricing_direct(
        self,
        object_name: str,
        region: str = 'eu-zurich-1',
    ) -> List[Dict]:
        """
        Download a pricing PDF and extract ALL pricing rows locally.

        Pipeline:
          DBMS_CLOUD.GET_OBJECT → bytes
            → pdfplumber  (geometry-aware table extraction)
              → OCIPDFParser  (pure-Python column mapping + price parsing)
                → List[pricing_cache row dicts]

        No API calls, no LLM, fully deterministic.  Much faster and cheaper
        than sending the document to Claude.

        Returns:
            List of pricing dicts ready for bulk_insert_pricing_data().
        """
        from utils.oci_pdf_parser import parse_oci_pricing_pdf_from_bytes

        object_uri = self._object_uri(object_name)
        logger.info(f"Local PDF extraction: downloading '{object_name}'...")

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DBMS_CLOUD.GET_OBJECT(:cred_name, :object_uri) FROM DUAL",
                {'cred_name': self.credential_name, 'object_uri': object_uri}
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                raise ValueError(
                    f"DBMS_CLOUD.GET_OBJECT returned nothing for '{object_name}'. "
                    "Verify the credential and object name."
                )
            blob_bytes = row[0].read()

        logger.info(f"Downloaded {len(blob_bytes):,} bytes — parsing locally...")

        results = parse_oci_pricing_pdf_from_bytes(
            blob_bytes,
            doc_name=object_name,
            region=region,
        )

        logger.info(
            f"Local extraction complete: {len(results)} pricing rows "
            f"from '{object_name}'"
        )
        return results


# Convenience function
def fetch_oci_documents(force_refresh: bool = False) -> Dict:
    """
    List, download, process, and embed all PDF documents from the OCI bucket.
    """
    client = OCIStorageClient()
    return client.process_and_store_documents(force_refresh)
