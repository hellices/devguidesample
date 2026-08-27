#!/usr/bin/env bash
# ACR → AMR 마이그레이션 전 애플리케이션 명령어 감사 (정적 스캔)
#
#   ./audit_commands.sh <소스 디렉터리> [<소스 디렉터리> ...]
#
# 소스 코드에서 AMR 전환 시 문제가 될 수 있는 Redis 명령을 등급별로 찾습니다.
# TIER 1 적중이 있으면 종료 코드 1로 끝납니다.
#
# 한계 — 이 스크립트만 믿으면 안 됩니다:
#   - 문자열로 명령을 조립하거나 프레임워크가 대신 호출하는 것은 잡히지 않습니다.
#     (예: Spring Session, Celery, Sidekiq, ORM 캐시 계층)
#   - 주석·변수명·다른 라이브러리의 동명 메서드가 오탐으로 잡힙니다.
#   - 실사용 명령의 확정적 근거는 소스 ACR의 런타임 관측입니다.
#     `INFO commandstats` 또는 짧은 `MONITOR` 표본을 병행하세요. (가이드 3.7절)

set -uo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <dir> [<dir> ...]" >&2
  exit 2
fi

DIRS=("$@")
MAX_SHOW=40

GREP_OPTS=(
  -rEniI
  --include=*.java --include=*.kt --include=*.scala --include=*.groovy
  --include=*.py --include=*.rb --include=*.go --include=*.rs --include=*.lua
  --include=*.js --include=*.ts --include=*.jsx --include=*.tsx --include=*.mjs
  --include=*.cs --include=*.php --include=*.ex --include=*.exs
  --include=*.yml --include=*.yaml --include=*.json
  --include=*.properties --include=*.conf --include=*.toml --include=*.env
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=vendor
  --exclude-dir=target --exclude-dir=build --exclude-dir=dist --exclude-dir=.venv
)

# bash 3.2(macOS 기본)에는 연관 배열이 없으므로 누산기 변수를 씁니다.
LAST_COUNT=0
T1=0; T2=0; T3=0; T4=0

# scan <등급> <제목> <설명> <정규식>
scan() {
  local tier="$1" title="$2" desc="$3" pattern="$4" hits n
  hits=$(grep "${GREP_OPTS[@]}" -e "$pattern" "${DIRS[@]}" 2>/dev/null || true)
  if [ -z "$hits" ]; then n=0; else n=$(printf '%s\n' "$hits" | wc -l | tr -d ' '); fi
  LAST_COUNT=$n

  printf '\n--- %s : %s건\n' "$title" "$n"
  [ -n "$desc" ] && printf '    %s\n' "$desc"
  if [ "$n" -gt 0 ]; then
    printf '%s\n' "$hits" | head -"$MAX_SHOW" | sed 's/^/    /'
    [ "$n" -gt "$MAX_SHOW" ] && printf '    ... (%d건 더)\n' "$((n - MAX_SHOW))"
  fi

  case "$tier" in
    1) T1=$((T1 + n)) ;;
    2) T2=$((T2 + n)) ;;
    3) T3=$((T3 + n)) ;;
    4) T4=$((T4 + n)) ;;
  esac
}

echo "감사 대상: ${DIRS[*]}"

echo ""
echo "===================================================================="
echo "TIER 1 — 클러스터 정책과 무관하게 반드시 조치해야 하는 항목"
echo "===================================================================="

scan 1 "다중 데이터베이스 사용" \
  "AMR은 데이터베이스 0 하나만 지원합니다. SELECT/MOVE/SWAPDB와 연결 설정의 DB 번호를 모두 없애야 합니다." \
  '(select[[:space:]]*\([[:space:]]*[1-9]|\bswapdb\b|\bmove[[:space:]]*\(|getdatabase[[:space:]]*\([[:space:]]*[1-9]|defaultdatabase|\bdatabase[[:space:]]*[:=][[:space:]]*[1-9]|\bdb[[:space:]]*[:=][[:space:]]*[1-9]|redis://[^[:space:]"'"'"']+:[0-9]+/[1-9])'

scan 1 "키스페이스 알림 구독" \
  "문서는 AMR 미지원이라고 하지만 실측에서는 기본값 AKE로 동작했습니다. 지원 대상이 아닌 동작이므로 의존 여부를 판단해야 합니다." \
  '(__keyspace@|__keyevent@|notify-keyspace-events|RedisIndexedSessionRepository|EnableRedisIndexedHttpSession)'

echo ""
echo "===================================================================="
echo "TIER 2 — 크로스 슬롯 다중 키 명령 (EnterpriseCluster에서도 실패 가능)"
echo "===================================================================="
echo "허용 목록은 DEL·MSET·MGET·EXISTS·UNLINK·TOUCH 6개뿐입니다. 아래는 전부 그 밖입니다."
echo "→ 해시 태그로 같은 슬롯에 모으거나, 25GB 이하라면 NoCluster를 검토하세요."

scan 2 "집합/정렬셋 연산" "" \
  '\b(sinterstore|sunionstore|sdiffstore|sintercard|sinter|sunion|sdiff|smove|zunionstore|zinterstore|zdiffstore|zintercard|zrangestore|zunion|zinter|zdiff)\b'

scan 2 "리스트 이동 / 다중 키 블로킹" "" \
  '\b(rpoplpush|brpoplpush|lmove|blmove|lmpop|blmpop|blpop|brpop|bzpopmin|bzpopmax|bzmpop)\b'

scan 2 "키 이름 변경·복사·SORT STORE" "" \
  '(\brenamenx\b|\brename[[:space:]]*\(|\bcopy[[:space:]]*\(|\bsort\b[^\n]*\b(store|by|get)\b)'

scan 2 "비트 / HLL / 스트림 / GEO 다중 키" "" \
  '\b(bitop|pfmerge|pfcount|xread|xreadgroup|geosearchstore|geounionstore|\blcs\b|msetnx)\b'

scan 2 "트랜잭션 · Lua" \
  "명령 자체가 아니라 '묶인 키들이 같은 슬롯인가'가 관건입니다. 적중 건은 KEYS 인자를 직접 확인하세요." \
  '(\bmulti[[:space:]]*\(|\.multi\b|\bexec[[:space:]]*\(|\bevalsha\b|\beval[[:space:]]*\(|\bfcall\b|script_?load|\bwatch[[:space:]]*\()'

echo ""
echo "===================================================================="
echo "TIER 3 — OSSCluster를 선택할 경우에만 문제가 되는 항목"
echo "===================================================================="
echo "EnterpriseCluster에서는 그대로 동작합니다. OSSCluster라면 같은 슬롯 제약이 붙습니다."

scan 3 "허용 목록 6개 명령의 다중 키 호출" "" \
  '\b(mset|mget|unlink|touch|exists|del)[[:space:]]*\('

echo ""
echo "===================================================================="
echo "TIER 4 — 서버/관리 명령 (한쪽 또는 양쪽에서 차단)"
echo "===================================================================="

scan 4 "관리 명령 호출" \
  "ACR과 AMR의 차단 목록이 서로 다릅니다. ROLE/FAILOVER/SWAPDB는 ACR에서는 되고 AMR에서 안 됩니다." \
  '(\bconfig[[:space:]]*(set|get)\b|configset|configget|\bdebug[[:space:]]+(object|sleep|jmap)\b|bgrewriteaof|\bbgsave\b|\blastsave\b|\bflushall\b|\bflushdb\b|\bacl[[:space:]]+(setuser|deluser|load|save)\b|(\.|->|::)[[:space:]]*(shutdown|failover|role|migrate)[[:space:]]*\(|\breplicaof\b|\bslaveof\b)'


echo ""
echo "===================================================================="
echo "요약"
echo "===================================================================="
printf 'TIER 1 (필수 조치)        : %s건\n' "$T1"
printf 'TIER 2 (크로스 슬롯 위험) : %s건\n' "$T2"
printf 'TIER 3 (OSSCluster 한정)  : %s건\n' "$T3"
printf 'TIER 4 (관리 명령)        : %s건\n' "$T4"
echo ""
echo "TIER 1이 0건이 아니면 코드 변경 없이는 마이그레이션할 수 없습니다."
echo "TIER 2가 0건이면 EnterpriseCluster에서 무수정으로 동작할 가능성이 높습니다."
echo "TIER 2·3이 모두 0건이면 OSSCluster(성능 우위)를 검토하세요."
echo ""
echo "정적 스캔은 프레임워크가 대신 호출하는 명령을 놓칩니다."
echo "소스 ACR에서 INFO commandstats 또는 MONITOR 표본으로 반드시 교차 확인하세요."

[ "$T1" -gt 0 ] && exit 1
exit 0
