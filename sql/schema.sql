PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS filings (
    cik TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    company_name TEXT NOT NULL,
    form TEXT NOT NULL CHECK (form IN ('10-K', '10-Q')),
    filing_date TEXT NOT NULL,
    period_end TEXT NOT NULL,
    primary_document TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (cik, accession_number)
);

CREATE TABLE IF NOT EXISTS statement_items (
    cik TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    statement TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    source_tag TEXT,
    PRIMARY KEY (cik, accession_number, statement, metric),
    FOREIGN KEY (cik, accession_number)
        REFERENCES filings (cik, accession_number) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ratios (
    cik TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (cik, accession_number, metric),
    FOREIGN KEY (cik, accession_number)
        REFERENCES filings (cik, accession_number) ON DELETE CASCADE
);
