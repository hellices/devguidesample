# shellcheck shell=bash disable=SC2034  # 변수는 이 파일을 source하는 스크립트가 씁니다.
# bench·hooks·migrate 스크립트가 함께 쓰는 입력 검사, 호출 제한, 대기 함수입니다. source로 읽습니다.
LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# kubectl 요청 제한. 자체 --timeout으로 오래 기다리는 명령(rollout status 등)은 그보다 긴 값을 따로 줍니다.
KUBE_RT=60s
# bounded <초> <명령...>: 제한 시간을 넘기면 명령과 자식 프로세스를 끝내고 124를 반환합니다(bounded.py).
bounded() { python3 "$LIB_DIR/bounded.py" "$@"; }
azq() { bounded 300 az "$@"; }     # az 조회
azop() { bounded 3600 az "$@"; }   # 풀 추가·삭제·변경, 클러스터 변경 같은 장시간 az 작업

# int_arg <이름> <값> <최솟값>: 9자리 이하 정수이고 최솟값 이상이면 10진수로 정규화해 출력합니다.
# 앞자리 0(예: 08)을 8진수로 읽지 않습니다. 아니면 오류를 출력하고 2를 반환합니다.
int_arg() {
  if [[ $2 =~ ^0*([0-9]{1,9})$ ]] && (( 10#${BASH_REMATCH[1]} >= $3 )); then
    echo "$(( 10#${BASH_REMATCH[1]} ))"; return 0
  fi
  echo "${1} 값은 ${3} 이상의 정수여야 합니다: ${2}" >&2; return 2
}

# check_scenario <값>: CSV 첫 열과 결과 경로(OUT/<scenario>)에 그대로 쓰므로 열·행을 깨거나 경로를 벗어나는 값을 막습니다.
check_scenario() {
  [[ $1 =~ ^[A-Za-z0-9._-]+$ && $1 != . && $1 != .. ]] && return 0
  echo "scenario는 영문자, 숫자, '.', '_', '-'만 쓸 수 있고 '.'이나 '..'일 수 없습니다: ${1}" >&2; return 2
}

# split_selector <key=value>: Kubernetes label 문법의 key=value 하나면 SEL_KEY, SEL_VAL을 설정합니다.
# '=' 1개, key 필수, value는 비어도 됩니다. key: [DNS subdomain 접두사(253자 이하)/]이름(63자 이하),
# value: 빈 값 또는 이름과 같은 규칙. 나눈 key·value를 patch와 노드 조회에 함께 씁니다.
split_selector() {
  local name='[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?' dns='[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?'
  local key=${1%%=*} val=${1#*=} prefix
  if [[ $1 == *=* && $val != *=* && $key =~ ^(($dns)(\.$dns)*/)?$name$ && $val =~ ^($name)?$ ]]; then
    prefix=${key%/*}
    if [[ $key != */* || ${#prefix} -le 253 ]]; then SEL_KEY=$key SEL_VAL=$val; return 0; fi
  fi
  echo "nodeSelector는 Kubernetes label 문법의 key=value여야 합니다: ${1}" >&2; return 2
}

# count_matching <정규식>: 표준 입력에서 정규식과 맞는 줄 수를 출력합니다. 0개도 성공(0)으로 끝납니다.
count_matching() { awk -v re="$1" '$0 ~ re { n++ } END { print n + 0 }'; }

# wait_until <제한 초> <간격 초> <명령...>: 명령이 성공하면 0, 제한 시간이 지나면 1을 반환합니다.
# 확인할 때마다 마감을 보고, 마감 시각 이후에 끝난 확인은 성공이어도 timeout으로 봅니다.
# 명령의 조회 실패는 미충족으로 보고 다시 확인합니다. 확인 사이의 대기는 남은 시간을 넘기지 않습니다.
# 확인 명령은 현재 셸에서 실행해야 변수 설정(예: quota-staleness.sh의 released가 남기는 cur)이 유지되므로
# 여기서 강제로 끊지 않습니다. 대신 확인 명령마다 kubectl --request-timeout이나 azq·bounded로 자체 제한을 두며,
# 반환은 마감 뒤 최대 그 제한 시간만큼 늦어질 수 있습니다.
wait_until() {
  local limit=$1 step=$2 deadline left; shift 2
  deadline=$(( $(date +%s) + limit ))
  while :; do
    if "$@"; then
      [[ $(date +%s) -lt $deadline ]] && return 0
      return 1
    fi
    left=$(( deadline - $(date +%s) ))
    (( left > 0 )) || return 1
    sleep "$(( left < step ? left : step ))"
  done
}
