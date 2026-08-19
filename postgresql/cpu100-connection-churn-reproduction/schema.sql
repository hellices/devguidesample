-- 1) 부모 테이블만 정의 (파티션 테이블)
CREATE TABLE IF NOT EXISTS public.store_kv (
  scope text NOT NULL,
  key text NOT NULL,
  value bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  part_month date NOT NULL DEFAULT (date_trunc('month', now() AT TIME ZONE 'UTC'))::date,
  ttl_policy text,
  ttl_policy_hash text,
  expires_at timestamptz
) PARTITION BY RANGE (part_month);

CREATE TABLE IF NOT EXISTS public.store_stream (
  scope text NOT NULL,
  seq bigint NOT NULL,
  key text,
  record bytea NOT NULL,
  event_ms bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  part_month date NOT NULL DEFAULT (date_trunc('month', now() AT TIME ZONE 'UTC'))::date,
  ttl_policy text,
  ttl_policy_hash text,
  expires_at timestamptz
) PARTITION BY RANGE (part_month);

CREATE TABLE IF NOT EXISTS public.store_sorted_set (
  scope text NOT NULL,
  member text NOT NULL,
  score double precision NOT NULL DEFAULT 0.0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  part_month date NOT NULL DEFAULT (date_trunc('month', now() AT TIME ZONE 'UTC'))::date,
  ttl_policy text,
  ttl_policy_hash text,
  expires_at timestamptz
) PARTITION BY RANGE (part_month);

-- 비파티션 테이블
CREATE TABLE IF NOT EXISTS public.store_stream_offsets (
  scope text NOT NULL,
  consumed_seq bigint NOT NULL DEFAULT 0
);

-- 시퀀스 카운터 (replay.py의 op_seq_counter가 사용)
CREATE TABLE IF NOT EXISTS public.seq_counter (
  id bigint NOT NULL,
  update_time timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT seq_counter_pk PRIMARY KEY (id)
);

-- 2) 부모 제약/인덱스만 정의 (자식에 자동 전파/생성)
ALTER TABLE public.store_kv
  ADD CONSTRAINT store_kv_pkey PRIMARY KEY (scope, key, part_month);
ALTER TABLE public.store_stream
  ADD CONSTRAINT store_stream_pkey PRIMARY KEY (scope, seq, part_month);
ALTER TABLE public.store_sorted_set
  ADD CONSTRAINT store_sorted_set_pkey PRIMARY KEY (scope, member, part_month);
ALTER TABLE public.store_stream_offsets
  ADD CONSTRAINT store_stream_offsets_pkey PRIMARY KEY (scope);

CREATE INDEX IF NOT EXISTS idx_store_kv_expires_at_due ON public.store_kv (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_store_kv_scope ON public.store_kv (scope);
CREATE INDEX IF NOT EXISTS idx_store_kv_scope_prefix ON public.store_kv (scope text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_store_kv_updated_at ON public.store_kv (updated_at);

CREATE INDEX IF NOT EXISTS idx_store_stream_created_at ON public.store_stream (created_at);
CREATE INDEX IF NOT EXISTS idx_store_stream_expires_at_due ON public.store_stream (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_store_stream_scope ON public.store_stream (scope);
CREATE INDEX IF NOT EXISTS idx_store_stream_scope_prefix ON public.store_stream (scope text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_store_sorted_set_expires_at_due ON public.store_sorted_set (expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_store_sorted_set_scope_prefix ON public.store_sorted_set (scope text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_store_sorted_set_ns_score_member ON public.store_sorted_set (scope, score, member);
CREATE INDEX IF NOT EXISTS idx_store_sorted_set_updated_at ON public.store_sorted_set (updated_at);

CREATE INDEX IF NOT EXISTS idx_store_stream_offsets_scope_prefix ON public.store_stream_offsets (scope text_pattern_ops);

-- 3) 월 파티션 자동 생성 함수
CREATE OR REPLACE FUNCTION public.ensure_monthly_partitions(
  p_parent_table text,
  p_from_month date,
  p_to_month date
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_month date := date_trunc('month', p_from_month)::date;
  v_end   date := date_trunc('month', p_to_month)::date;
  v_child text;
BEGIN
  WHILE v_month < v_end LOOP
    v_child := format('%s_%s', p_parent_table, to_char(v_month, 'YYYY_MM'));
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS public.%I PARTITION OF public.%I FOR VALUES FROM (%L) TO (%L)',
      v_child, p_parent_table, v_month, (v_month + interval '1 month')::date
    );
    v_month := (v_month + interval '1 month')::date;
  END LOOP;
END;
$$;

-- 4) 필요한 범위 한번에 생성 (예: 2025-11 ~ 2026-11)
SELECT public.ensure_monthly_partitions('store_kv',         '2025-11-01', '2026-11-01');
SELECT public.ensure_monthly_partitions('store_stream',        '2025-11-01', '2026-11-01');
SELECT public.ensure_monthly_partitions('store_sorted_set', '2025-11-01', '2026-11-01');