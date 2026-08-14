ALTER TABLE remediation_proposals
    ADD COLUMN IF NOT EXISTS status LowCardinality(String) DEFAULT 'proposed';

ALTER TABLE remediation_proposals
    ADD COLUMN IF NOT EXISTS outcome String DEFAULT '';

ALTER TABLE remediation_proposals
    ADD COLUMN IF NOT EXISTS executed UInt8 DEFAULT 0;
