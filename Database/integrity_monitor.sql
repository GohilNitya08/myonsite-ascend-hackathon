-- Document Integrity Monitor Schema
-- Two tables: document_events + document_audit_snapshots

CREATE TABLE document_events (
    event_id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    event_type ENUM('edit', 'delete', 'metadata_update', 'comment', 'share') NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    event_timestamp DATETIME(6) NOT NULL,
    content TEXT NULL,
    metadata JSON NULL,
    source VARCHAR(50) NOT NULL,
    normalized_payload JSON NOT NULL,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    KEY idx_document_timestamp (document_id, event_timestamp)
);

CREATE TABLE document_audit_snapshots (
    document_id VARCHAR(255) PRIMARY KEY,
    resolved JSON NOT NULL,
    conflicts JSON NOT NULL,
    tampering_alerts JSON NOT NULL,
    audit_log JSON NOT NULL,
    event_count INT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
