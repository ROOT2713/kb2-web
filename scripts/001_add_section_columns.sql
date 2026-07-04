-- Migration: Add section_type and section_header to parent_chunks
-- Phase 1b: parent_chunks结构化
-- Run: sqlite3 /home/ubuntu/kb-web/data/kb.db < scripts/001_add_section_columns.sql

ALTER TABLE parent_chunks ADD COLUMN section_type TEXT;
ALTER TABLE parent_chunks ADD COLUMN section_header TEXT;
