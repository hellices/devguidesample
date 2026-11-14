-- Run as the HorizonDB administrator against the "movielog" database after data/embed_catalog.py.
-- DiskANN approximate nearest-neighbor index for cosine distance (<=>) on 1,536-dimension embeddings.
\set ON_ERROR_STOP on

CREATE INDEX IF NOT EXISTS movie_docs_embedding_diskann
	ON catalog.movie_docs USING diskann (embedding vector_cosine_ops);

ANALYZE catalog.movie_docs;

SELECT count(*) AS documents, count(embedding) AS embedded FROM catalog.movie_docs;
