#!/usr/bin/env bash
# azd postdeploy hook: PATTERN 환경 값에 적은 요청 수 기반 확장 패턴을 차례로 실행하고 결과를 out/<azd 환경>/에 남깁니다.
#   azd env set PATTERN "prometheus-rps http-add-on-min1"   # 공백 또는 쉼표로 여러 개
#   azd hooks run postdeploy                                # 또는 azd deploy
# 패턴: prometheus-rps http-add-on-min1 http-add-on-min0 http-add-on-cold-start azure-monitor-agc
# 패턴마다 이전 ScaledObject를 지우고 워크로드 노드가 줄어든 뒤 시작합니다. cold-start를 뺀 패턴은 같은 k6 부하
# (최대 초당 400건)를 주고, cold-start는 0개에서 첫 요청 응답 시간만 잽니다.
# 실패하거나 중단되면 k6·watcher Job, keeper, 임시 curl Pod를 지웁니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_SUBSCRIPTION_ID:?}" "${AZURE_RESOURCE_GROUP:?}" "${AKS_CLUSTER_NAME:?}" "${KEDA_CLIENT_ID:?}" "${AMW_QUERY_ENDPOINT:?}" "${AZURE_ENV_NAME:?}"
die() { echo "$*" >&2; exit 1; }
GUID_RE='^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$'
# 값은 sed 치환·경로·kube context에 쓰이므로 kubectl·az 호출 전에 형식을 확인합니다.
[[ $AZURE_ENV_NAME =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "AZURE_ENV_NAME 형식이 올바르지 않습니다: '${AZURE_ENV_NAME}'"
[[ $AKS_CLUSTER_NAME =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || die "AKS_CLUSTER_NAME 형식이 올바르지 않습니다: '${AKS_CLUSTER_NAME}'"
[[ $AZURE_SUBSCRIPTION_ID =~ $GUID_RE ]] || die "AZURE_SUBSCRIPTION_ID는 GUID여야 합니다: '${AZURE_SUBSCRIPTION_ID}'"
[[ $KEDA_CLIENT_ID =~ $GUID_RE ]] || die "KEDA_CLIENT_ID는 GUID여야 합니다: '${KEDA_CLIENT_ID}'"
[[ $AMW_QUERY_ENDPOINT =~ ^https://[A-Za-z0-9.-]+/?$ ]] || die "AMW_QUERY_ENDPOINT는 https://<호스트> 형식이어야 합니다: '${AMW_QUERY_ENDPOINT}'"
ENABLE_AGC=${ENABLE_AGC:-true}
[[ $ENABLE_AGC == true || $ENABLE_AGC == false ]] || die "ENABLE_AGC는 true 또는 false여야 합니다: '${ENABLE_AGC}'"
export CTX=$AKS_CLUSTER_NAME
OUT=out/$AZURE_ENV_NAME
# watcher 기록 시간(초). load/watcher.yaml의 DURATION과 같게 둡니다.
WATCH_SECONDS=1200
INTERCEPTOR=http://keda-add-ons-http-interceptor-proxy.kube-system:8080/
HOST=podinfo.example.com
log() { echo "[$(date -u +%T)] $*" >&2; }

# 로컬 네트워크가 잠시 끊겨도 실험이 멈추지 않도록 kubectl을 최대 6번(10초 간격) 다시 시도합니다.
# 반복해도 결과가 같은 조회·적용·삭제에만 씁니다. API 호출이 멈춰도 다음 시도로 넘어가도록 요청마다 --request-timeout을 둡니다.
kretry() { # kretry <request-timeout> <kubectl 인수...>
  local rt=$1 i out; shift
  for i in 1 2 3 4 5 6; do
    # 실패한 시도의 부분 출력이 섞이지 않게 성공한 시도의 출력만 내보냅니다.
    if out=$(kubectl --context "$CTX" --request-timeout="$rt" "$@"); then
      [[ -z $out ]] || printf '%s\n' "$out"
      return 0
    fi
    (( i < 6 )) && sleep 10
  done
  return 1
}
k() { kretry 30s "$@"; }
# --request-timeout은 watch 요청도 끊으므로 자체 --timeout까지 기다리는 rollout status·delete(기본 --wait=true)는
# 이 함수로 대기 시간을 함께 지정하고 요청 제한을 대기 시간보다 1분 길게 둡니다.
kwait() { # kwait <대기 분> <kubectl 인수...>
  local m=$1; shift
  kretry "$(( m + 1 ))m" "$@" --timeout="${m}m"
}
kapply() { # kapply <manifest>: 같은 내용을 최대 6번 적용합니다.
  local i
  [[ -n $1 ]] || { echo "적용할 manifest가 비어 있습니다" >&2; return 1; }
  for i in 1 2 3 4 5 6; do
    kubectl --context "$CTX" --request-timeout=30s apply -f - <<<"$1" >/dev/null && return 0
    (( i < 6 )) && sleep 10
  done
  return 1
}
# kubectl 출력을 시도마다 파일에 새로 씁니다(부분 출력이 이어 붙지 않게).
kto() {
  local f=$1 i; shift
  for i in 1 2 3 4 5 6; do
    kubectl --context "$CTX" --request-timeout=30s "$@" > "$f" && return 0
    (( i < 6 )) && sleep 10
  done
  return 1
}
# 아래 조건 함수가 쓰는 한 번짜리 조회입니다. 실패는 wait_until이 다음 확인에서 다시 봅니다.
kq() { kubectl --context "$CTX" --request-timeout=30s "$@"; }
# 빈 줄을 뺀 줄 수. grep의 "일치 없음"(1)만 0으로 보고 그 밖의 오류는 실패로 돌려줍니다.
count_lines() { grep -c . <<<"$1" || [[ $? == 1 ]]; }

wait_until() { # wait_until <설명> <제한 초> <조건 명령...>
  # 절대 마감 시각을 두고 조건 실행 전후에 확인합니다. 마감 뒤에는 조건을 새로 실행하지 않고,
  # 조건이 성공해도 마감을 넘겨 끝났으면 시간 초과로 처리합니다.
  # 조건은 0(충족), 1(아직), 그 밖(즉시 실패)을 돌려주며 stderr에 남긴 마지막 상태를 실패 메시지에 붙입니다.
  local what=$1 limit=$2; shift 2
  local deadline=$(( SECONDS + limit )) rest rc err=""
  while (( SECONDS < deadline )); do
    rc=0; err=$("$@" 2>&1 >/dev/null) || rc=$?
    if (( rc == 0 )); then
      (( SECONDS < deadline )) && return 0
      break
    fi
    if (( rc != 1 )); then
      echo "${what}: 실패했습니다${err:+ - $err}" >&2; return 1
    fi
    rest=$(( deadline - SECONDS ))
    (( rest > 0 )) || break
    sleep $(( rest < 10 ? rest : 10 ))
  done
  echo "${what}: ${limit}초 안에 끝나지 않았습니다${err:+ (마지막 상태: $err)}" >&2; return 1
}

# 조건 함수: 조회가 실패하면 1(아직)을 돌려줘 실패한 조회를 노드 0대·Pod 0개로 읽지 않습니다.
user_nodes() { # 워크로드 노드 수를 출력합니다. 조회 실패는 실패로 돌려줍니다.
  local out; out=$(k get nodes -l kubernetes.azure.com/mode=user -o name) || return 1
  count_lines "$out"
}
nodes_at_most() { # nodes_at_most <n>: 워크로드 노드가 n대 이하이면 성공
  local out n
  out=$(kq get nodes -l kubernetes.azure.com/mode=user -o name) || return 1
  n=$(count_lines "$out") || return 1
  (( n <= $1 )) || { echo "워크로드 노드 ${n}대" >&2; return 1; }
}
no_podinfo_pods() { # Deployment 집계와 Pod 객체가 모두 0일 때 성공
  local rep pods
  rep=$(kq -n demo get deploy podinfo -o jsonpath='{.status.replicas}') || return 1
  pods=$(kq -n demo get pods -l app=podinfo -o name) || return 1
  [[ $rep =~ ^0?$ && -z $pods ]] || { echo "replica ${rep:-0}, Pod 남음" >&2; return 1; }
}
podinfo_scaled_to_zero() { # Deployment가 replica 0을 원하면 성공
  local r; r=$(kq -n demo get deploy podinfo -o jsonpath='{.spec.replicas}') || return 1
  [[ $r == 0 ]] || { echo "spec.replicas=${r}" >&2; return 1; }
}
podinfo_exactly() { # podinfo_exactly <n>: 원하는·현재·사용 가능 replica와 종료 중이 아닌 Pod가 모두 정확히 n개이면 성공
  local st pods spec cur avail
  st=$(kq -n demo get deploy podinfo -o jsonpath='{.spec.replicas} {.status.replicas} {.status.availableReplicas}') || return 1
  pods=$(kq -n demo get pods -l app=podinfo -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}') || return 1
  pods=$(count_lines "$pods") || return 1
  read -r spec cur avail <<<"$st"
  [[ ${spec:-0} == "$1" && ${cur:-0} == "$1" && ${avail:-0} == "$1" && $pods == "$1" ]] ||
    { echo "spec ${spec:-0}, replicas ${cur:-0}, available ${avail:-0}, Pod ${pods}개" >&2; return 1; }
}
no_podinfo_hpa() { # demo에서 Deployment podinfo를 대상으로 하는 HPA가 없으면 성공
  local rows name target found=""
  rows=$(kq -n demo get hpa -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.scaleTargetRef.kind}/{.spec.scaleTargetRef.name}{"\n"}{end}') || return 1
  while read -r name target; do
    [[ $target == Deployment/podinfo ]] && found+=" $name"
  done <<<"$rows"
  [[ -z $found ]] || { echo "podinfo를 대상으로 하는 HPA:${found}" >&2; return 1; }
}
scaledobject_ready() { # ScaledObject podinfo의 Ready 조건이 True이면 성공
  local s
  s=$(kq -n demo get scaledobject podinfo -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{" "}{.message}{end}') || return 1
  [[ $s == True* ]] || { echo "Ready=${s:-없음}" >&2; return 1; }
}
job_finished() { # job_finished <Job 이름>: Complete면 0, Failed면 2(즉시 실패), 아직이면 1
  local s
  s=$(kq -n demo get job "$1" -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{end}') || return 1
  case " $s " in
    *" Complete "*) return 0 ;;
    *" Failed "*) echo "Job ${1}이 실패했습니다" >&2; return 2 ;;
  esac
  return 1
}
pod_finished() { # pod_finished <Pod 이름>: Succeeded면 0, Failed면 2(즉시 실패), 아직이면 1
  local p; p=$(kq -n demo get pod "$1" -o jsonpath='{.status.phase}') || return 1
  case $p in
    Succeeded) return 0 ;;
    Failed) echo "Pod ${1}이 실패했습니다" >&2; return 2 ;;
  esac
  echo "phase=${p}" >&2; return 1
}
job_pod_started() { # job_pod_started <Job uid>: 이 Job의 Pod가 하나이고 컨테이너가 시작했으면 "<Pod 이름> <시작 시각>"을 출력
  local rows n re='^[a-z0-9.-]+ [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$'
  rows=$(kq -n demo get pods -l "batch.kubernetes.io/controller-uid=$1" \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].state.*.startedAt}{"\n"}{end}') || return 1
  n=$(count_lines "$rows") || return 1
  (( n <= 1 )) || { echo "Job Pod가 ${n}개입니다" >&2; return 2; }
  [[ $rows =~ $re ]] || { echo "컨테이너 시작 전" >&2; return 1; }
  printf '%s\n' "$rows"
}
watcher_recording() { # watcher_recording <Job uid>: 실행 중인 watcher Pod가 하나이고 첫 기록을 남겼으면 "pod/<이름>"을 출력
  local pods n out
  pods=$(kq -n demo get pods -l "batch.kubernetes.io/controller-uid=$1" --field-selector=status.phase=Running -o name) || return 1
  n=$(count_lines "$pods") || return 1
  (( n == 1 )) || { echo "실행 중인 watcher Pod ${n}개" >&2; return 1; }
  out=$(kq -n demo logs "$pods") || return 1
  grep -qE '^[0-9]+,' <<<"$out" || { echo "watcher 첫 기록 전" >&2; return 1; }
  printf '%s\n' "$pods"
}
gateway_has_address() {
  local a; a=$(kq -n demo get gateway web -o jsonpath='{.status.addresses[*].value}') || return 1
  [[ -n $a ]] || { echo "Gateway 주소 없음" >&2; return 1; }
}

reset() { # 이전 패턴의 scaler와 부하를 지우고 podinfo를 replica <n>, 워크로드 노드를 <n>대 이하로 맞춥니다.
  kwait 5 -n demo delete scaledobject podinfo --ignore-not-found >/dev/null
  kwait 5 -n demo delete triggerauthentication azure-wi --ignore-not-found >/dev/null
  kwait 5 -n demo delete interceptorroute podinfo --ignore-not-found >/dev/null
  # foreground 삭제로 Job의 Pod까지 사라진 뒤 넘어갑니다(이전 실행의 Pod를 이번 실행으로 읽지 않게).
  kwait 5 -n demo delete job k6 watcher --ignore-not-found --cascade=foreground >/dev/null
  # 이전 실행이 중간에 멈춰 남은 keeper·임시 Pod가 노드를 붙잡지 않도록 지웁니다.
  kwait 5 -n demo delete deploy keeper --ignore-not-found >/dev/null
  kwait 5 -n demo delete pod -l keda-lab=probe --ignore-not-found >/dev/null
  # KEDA admission webhook에 기대지 않고 podinfo를 대상으로 하는 HPA가 남지 않았는지 확인합니다.
  wait_until "podinfo 대상 HPA 제거" 300 no_podinfo_hpa
  k -n demo scale deploy podinfo --replicas "$1" >/dev/null
  log "워크로드 노드가 ${1}대 이하가 될 때까지 대기(NAP consolidation)"
  wait_until "노드 축소" 1800 nodes_at_most "$1"
  # podinfo가 Pending이거나 이전 패턴의 Pod가 남은 채로 warm 패턴이 시작되지 않도록 정확히 replica <n>개가 될 때까지 기다립니다.
  if (( $1 >= 1 )); then
    log "podinfo replica 정확히 ${1}개 대기"
    wait_until "podinfo 준비" 900 podinfo_exactly "$1"
  fi
}
apply_scaledobject() { # apply_scaledobject <manifest>
  kapply "$1"
  wait_until "ScaledObject Ready" 300 scaledobject_ready
}
apply_http_scaler() { # apply_http_scaler <minReplicaCount>
  local m; m=$(sed "s/minReplicaCount: 0/minReplicaCount: $1/" http-add-on/scaling.yaml)
  apply_scaledobject "$m"
}
PROBE_OUT=""
run_probe() { # run_probe <Pod 이름> <제한 초> <sh 스크립트>: 시스템 노드의 임시 curl Pod에서 실행하고 출력을 PROBE_OUT에 담습니다.
  local name=$1 limit=$2 m
  m=$(python3 -c '
import json, sys
name, script = sys.argv[1:3]
print(json.dumps({"apiVersion": "v1", "kind": "Pod",
  "metadata": {"name": name, "namespace": "demo", "labels": {"keda-lab": "probe"}},
  "spec": {"restartPolicy": "Never",
    "nodeSelector": {"kubernetes.azure.com/mode": "system"},
    "tolerations": [{"key": "CriticalAddonsOnly", "operator": "Exists"}],
    "containers": [{"name": "curl", "image": "curlimages/curl:8.23.0", "command": ["sh", "-c", script],
      "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}}}]}}))' "$name" "$3")
  kapply "$m"
  wait_until "임시 Pod ${name} 종료" "$limit" pod_finished "$name"
  PROBE_OUT=$(k -n demo logs "pod/$name")
  kwait 2 -n demo delete pod "$name" --ignore-not-found >/dev/null
}
run_load() { # run_load <결과 이름> <TARGET_URL> [Host 헤더]
  local name=$1 target=$2 host=${3:-} m w_uid k6_uid wpod row k6_pod started k6_start phase
  # 같은 이름으로 다시 실행할 때 중간에 실패하면 이전 실행 결과가 남아 섞이므로 먼저 지웁니다.
  rm -f "$OUT/$name-k6.txt" "$OUT/$name.raw" "$OUT/$name.csv"
  # 기록은 클러스터 안의 watcher Job이 합니다. 로컬 네트워크가 끊겨도 간격이 유지됩니다.
  # 같은 이름의 Job이 남아 있으면 apply가 이전 Job을 재사용하므로 Pod까지 지운 뒤 만듭니다.
  kwait 5 -n demo delete job watcher k6 --ignore-not-found --cascade=foreground >/dev/null
  m=$(k -n demo create configmap watch-script --from-file=load/watch-replicas.sh --dry-run=client -o yaml)
  kapply "$m"
  m=$(<load/watcher.yaml)
  kapply "$m"
  w_uid=$(k -n demo get job watcher -o jsonpath='{.metadata.uid}')
  [[ -n $w_uid ]] || { echo "watcher Job uid를 읽지 못했습니다" >&2; return 1; }
  # watcher가 첫 기록을 남긴 뒤 부하를 시작합니다(이미지 준비 시간만큼 기록이 늦게 시작되는 것을 막음).
  wait_until "watcher 시작" 300 watcher_recording "$w_uid"
  wpod=$(watcher_recording "$w_uid") || { echo "기록 중인 watcher Pod를 확인하지 못했습니다" >&2; return 1; }
  m=$(sed -e "s|value: http://podinfo.demo.svc/|value: $target|" -e "s|value: \"\"|value: \"$host\"|" load/k6-job.yaml)
  kapply "$m"
  k6_uid=$(k -n demo get job k6 -o jsonpath='{.metadata.uid}')
  [[ -n $k6_uid ]] || { echo "k6 Job uid를 읽지 못했습니다" >&2; return 1; }
  log "${name}: k6 부하 시작(6분 30초), replica·노드 기록 ${WATCH_SECONDS}초"
  # 이번 Job uid의 Pod만 봅니다. 시작 시각은 k6 컨테이너 시작 시각입니다.
  wait_until "k6 시작" 300 job_pod_started "$k6_uid"
  row=$(job_pod_started "$k6_uid") || { echo "k6 Pod 시작 시각을 읽지 못했습니다" >&2; return 1; }
  k6_pod=${row%% *} started=${row#* }
  k6_start=$(python3 -c "import datetime,sys;print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))" "$started")
  # k6가 threshold(실패율 50% 이상 등)로 실패하면 원인을 볼 수 있도록 로그를 남긴 뒤 멈춥니다.
  wait_until "k6 종료" 1200 job_finished k6 || {
    kto "$OUT/$name-k6.txt" -n demo logs "pod/$k6_pod" || true
    echo "k6가 실패했습니다. ${OUT}/${name}-k6.txt를 확인하세요(대상 URL·연결·실패율 threshold)" >&2; return 1; }
  kto "$OUT/$name-k6.txt" -n demo logs "pod/$k6_pod"
  wait_until "watcher 종료" $(( WATCH_SECONDS + 300 )) job_finished watcher
  # 부하 시작 전부터 기록하던 Pod가 끝까지 기록했을 때만 결과로 씁니다(재시도 Pod는 부하 구간 일부가 빠짐).
  phase=$(k -n demo get "$wpod" -o jsonpath='{.status.phase}')
  [[ $phase == Succeeded ]] || { echo "부하 전부터 기록하던 ${wpod}가 끝까지 기록하지 못했습니다(phase=${phase})" >&2; return 1; }
  kto "$OUT/$name.raw" -n demo logs "$wpod"
  # epoch를 k6 컨테이너 시작 시각 기준 경과 초로 바꿉니다. 음수는 부하 전 기록입니다.
  awk -F, -v t0="$k6_start" 'BEGIN{OFS=","; print "elapsed_s,desired,ready,hpa_metric,user_nodes"} /^[0-9]+,/{$1=$1-t0; print}' "$OUT/$name.raw" > "$OUT/$name.csv"
}
pattern_prometheus_rps() {
  local m
  reset 1
  m=$(sed -e "s|<keda-client-id>|$KEDA_CLIENT_ID|" -e "s|<amw-query-endpoint>|$AMW_QUERY_ENDPOINT|" prometheus/scaledobject.yaml)
  apply_scaledobject "$m"
  run_load prometheus-rps http://podinfo.demo.svc/
}
pattern_http_add_on_min1() { reset 1; apply_http_scaler 1; run_load http-add-on-min1 "$INTERCEPTOR" "$HOST"; }
pattern_http_add_on_min0() {
  reset 1; apply_http_scaler 0
  # Pod와 워크로드 노드가 모두 사라져 첫 요청에 새 노드가 필요한 상태에서 시작합니다.
  log "replica 0, Pod 0개, 워크로드 노드 0대 대기"
  wait_until "replica 0" 900 no_podinfo_pods
  wait_until "워크로드 노드 0" 1800 nodes_at_most 0
  run_load http-add-on-min0 "$INTERCEPTOR" "$HOST"
}
cold_request() { # cold_request <run 이름>: 0개 상태에서 첫 요청과 직후 warm 요청을 시스템 노드의 임시 Pod에서 보냅니다.
  local before ts
  # Deployment 집계가 0이어도 종료 중인 Pod가 남을 수 있으므로 Pod 객체가 모두 사라진 뒤 요청합니다.
  wait_until "replica 0, Pod 0개" 900 no_podinfo_pods
  before=$(user_nodes)
  ts=$(date +%s)
  # 첫 요청 300초, warm 요청 60초 제한에 Pod 준비 시간을 더해 600초 안에 끝나야 합니다.
  run_probe "coldstart-$1-$ts" 600 \
    "h=\$(curl -s -o /dev/null -D - -m 300 -w 'code=%{http_code} total=%{time_total}' -H 'Host: $HOST' $INTERCEPTOR | tr -d '\r' | grep -i -E 'x-keda-http-cold-start|code=' | tr '\n' ' ');
     w=\$(curl -sf -o /dev/null -m 60 -w '%{time_total}' -H 'Host: $HOST' $INTERCEPTOR) || w=failed; echo \"\$h warm_after=\$w\""
  echo "run=$1 user_nodes_before=$before $PROBE_OUT" | tee -a "$OUT/http-add-on-cold-start.txt"
}
pattern_http_add_on_cold_start() {
  local m n r
  # cold_request가 결과를 이어 쓰므로 패턴을 시작할 때 이전 결과를 한 번 비웁니다.
  : > "$OUT/http-add-on-cold-start.txt"
  reset 1; apply_http_scaler 0
  # 기존 노드에 자리가 있는 경우: 작은 keeper Pod로 워크로드 노드 1대를 유지합니다.
  # 시스템 노드에 배치되지 않도록 워크로드 노드(mode=user)만 고릅니다.
  m=$(k -n demo create deployment keeper --image=registry.k8s.io/pause:3.10 --dry-run=client -o yaml |
    kubectl patch --local -f - --type merge -o yaml \
      -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.azure.com/mode":"user"}}}}}')
  kapply "$m"
  k -n demo set resources deploy keeper --requests=cpu=100m,memory=64Mi >/dev/null
  kwait 10 -n demo rollout status deploy keeper >/dev/null
  n=$(user_nodes)
  (( n >= 1 )) || { echo "keeper 배치 뒤 워크로드 노드가 없습니다(${n}대)" >&2; return 1; }
  for r in 1 2 3; do cold_request "$r"; done
  # 새 노드가 필요한 경우: keeper를 지우고 워크로드 노드가 0대가 된 뒤 요청합니다.
  kwait 5 -n demo delete deploy keeper --ignore-not-found >/dev/null
  wait_until "replica 0" 900 podinfo_scaled_to_zero
  wait_until "워크로드 노드 0" 1800 nodes_at_most 0
  cold_request node-cold
}
pattern_azure_monitor_agc() {
  local cur want mc ids n alb tenant addr m ts
  # 부하·클러스터를 바꾸기 전에 AGC 조회와 값 확인을 먼저 끝냅니다.
  # az의 현재 구독이 azd 환경과 다르면 다른 구독의 리소스를 읽으므로 중단합니다.
  cur=$(az account show --query id -o tsv | tr 'A-F' 'a-f')
  want=$(tr 'A-F' 'a-f' <<<"$AZURE_SUBSCRIPTION_ID")
  [[ $cur == "$want" ]] ||
    { echo "az 현재 구독(${cur})이 AZURE_SUBSCRIPTION_ID와 다릅니다. az account set --subscription으로 맞추세요." >&2; return 1; }
  tenant=$(az account show --query tenantId -o tsv)
  [[ $tenant =~ $GUID_RE ]] || { echo "테넌트 ID를 읽지 못했습니다: '${tenant}'" >&2; return 1; }
  mc=$(az aks show -g "$AZURE_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --query nodeResourceGroup -o tsv)
  [[ $mc =~ ^[A-Za-z0-9._()-]+$ ]] || { echo "노드 리소스 그룹 이름이 올바르지 않습니다: '${mc}'" >&2; return 1; }
  # 어느 AGC의 지표로 확장할지 정할 수 없으므로 정확히 하나일 때만 진행합니다.
  ids=$(az resource list -g "$mc" --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[].id" -o tsv)
  n=$(count_lines "$ids")
  (( n == 1 )) || { echo "노드 리소스 그룹 ${mc}에서 AGC(trafficController)를 ${n}개 찾았습니다. 정확히 1개여야 합니다." >&2; return 1; }
  alb=${ids##*/}
  [[ $alb =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo "AGC 이름 형식이 올바르지 않습니다: '${alb}'" >&2; return 1; }
  reset 1
  m=$(sed -e "s|<keda-client-id>|$KEDA_CLIENT_ID|" -e "s|<alb-resource-name>|$alb|" -e "s|<node-resource-group>|$mc|" \
      -e "s|<subscription-id>|$AZURE_SUBSCRIPTION_ID|" -e "s|<tenant-id>|$tenant|" agc/scaledobject.yaml)
  apply_scaledobject "$m"
  # Gateway 주소는 비동기로 채워지므로 값이 생길 때까지 기다린 뒤 읽고, 정확히 하나인지 확인합니다.
  wait_until "AGC Gateway 주소" 600 gateway_has_address
  addr=$(k -n demo get gateway web -o jsonpath='{.status.addresses[*].value}')
  [[ $addr =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Gateway 주소가 하나의 호스트 이름·IP가 아닙니다: '${addr}'" >&2; return 1; }
  # 서브넷 NSG는 클러스터 생성 뒤에 연결될 수 있으므로(구독 정책 등) 부하 직전에 다시 확인하고
  # 클러스터 안에서 frontend가 200을 돌려줄 때까지(최대 600초) 기다립니다.
  ./agc/allow-frontend.sh
  log "AGC frontend 응답 대기"
  ts=$(date +%s)
  run_probe "agc-check-$ts" 900 \
    "end=\$((\$(date +%s) + 600)); c=; while [ \"\$(date +%s)\" -lt \"\$end\" ]; do
       c=\$(curl -s -o /dev/null -m 5 -w '%{http_code}' 'http://$addr/'); [ \"\$c\" = 200 ] && { echo ready; exit 0; }; sleep 5;
     done; echo \"not-ready last=\$c\""
  [[ $PROBE_OUT == ready ]] || { echo "AGC frontend가 600초 안에 200을 돌려주지 않았습니다(${PROBE_OUT})" >&2; return 1; }
  run_load azure-monitor-agc "http://$addr/"
}

# PATTERN을 모두 확인한 뒤 실행합니다(뒤쪽 패턴 오류로 앞 패턴만 실행되고 멈추지 않게).
list=${PATTERN:-}; list=${list//,/ }; list=${list//$'\n'/ }
read -r -a pats <<<"$list"
# azd up도 이 hook을 실행하므로 값이 없으면 안내만 하고 끝냅니다.
(( ${#pats[@]} > 0 )) || { echo "실행할 실험이 없습니다. 예: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"; exit 0; }
seen=" "
for p in "${pats[@]}"; do
  [[ $p =~ ^[a-z0-9-]+$ ]] && declare -F "pattern_${p//-/_}" >/dev/null || die "알 수 없는 패턴: $p"
  [[ $seen != *" $p "* ]] || die "패턴이 중복되었습니다: $p"
  [[ $p != azure-monitor-agc || $ENABLE_AGC == true ]] || die "ENABLE_AGC=false 환경에서는 azure-monitor-agc를 실행할 수 없습니다"
  seen+="$p "
done

cleanup() { # 실패·중단 시 부하와 임시 리소스를 멈춥니다. 여러 번 실행해도 안전합니다.
  local rc=$?
  trap - EXIT
  if (( rc != 0 )); then
    log "실패 또는 중단(종료 코드 ${rc}): k6·watcher Job, keeper, 임시 Pod를 지웁니다"
    kq -n demo delete job k6 watcher --ignore-not-found --wait=false >/dev/null || log "정리 실패: Job k6·watcher"
    kq -n demo delete deploy keeper --ignore-not-found --wait=false >/dev/null || log "정리 실패: Deployment keeper"
    kq -n demo delete pod -l keda-lab=probe --ignore-not-found --wait=false >/dev/null || log "정리 실패: 임시 Pod"
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$OUT"
for p in "${pats[@]}"; do
  log "패턴 $p 시작"; "pattern_${p//-/_}"; log "패턴 $p 완료"
done
reset 1
echo "결과: $OUT"
