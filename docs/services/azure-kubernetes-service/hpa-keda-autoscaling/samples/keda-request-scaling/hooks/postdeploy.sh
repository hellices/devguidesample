#!/usr/bin/env bash
# azd postdeploy hook: PATTERN 환경 값에 적은 요청 수 기반 확장 패턴을 차례로 실행하고 결과를 out/<azd 환경>/에 남깁니다.
#   azd env set PATTERN "prometheus-rps http-add-on-min1"   # 공백 또는 쉼표로 여러 개
#   azd hooks run postdeploy                                # 또는 azd deploy
# 패턴: prometheus-rps http-add-on-min1 http-add-on-min0 http-add-on-cold-start azure-monitor-agc
# 패턴마다 이전 ScaledObject를 지우고 워크로드 노드가 줄어든 뒤 같은 k6 부하(최대 초당 400건)를 줍니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_RESOURCE_GROUP:?}" "${AKS_CLUSTER_NAME:?}" "${KEDA_CLIENT_ID:?}" "${AMW_QUERY_ENDPOINT:?}" "${AZURE_ENV_NAME:?}"
export CTX=$AKS_CLUSTER_NAME
OUT=out/$AZURE_ENV_NAME; mkdir -p "$OUT"
# 로컬 네트워크가 잠시 끊겨도 실험이 멈추지 않도록 kubectl을 최대 6번(10초 간격) 다시 시도합니다.
# 반복해도 결과가 같은 조회·적용·삭제에만 씁니다. 요청을 보내는 cold start 측정은 kubectl을 직접 호출합니다.
k() { local i; for i in 1 2 3 4 5 6; do kubectl --context "$CTX" "$@" && return 0; sleep 10; done; return 1; }
# 표준 입력의 manifest를 한 번 읽어 두고 시도마다 같은 내용으로 적용합니다.
kapply() { local m i; m=$(cat); for i in 1 2 3 4 5 6; do kubectl --context "$CTX" apply -f - <<<"$m" >/dev/null && return 0; sleep 10; done; return 1; }
# kubectl 출력을 시도마다 파일에 새로 씁니다(부분 출력이 이어 붙지 않게).
kto() { local f=$1 i; shift; for i in 1 2 3 4 5 6; do kubectl --context "$CTX" "$@" > "$f" && return 0; sleep 10; done; return 1; }
log() { echo "[$(date -u +%T)] $*" >&2; }
INTERCEPTOR=http://keda-add-ons-http-interceptor-proxy.kube-system:8080/
HOST=podinfo.example.com

user_nodes() { k get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l | tr -d ' '; }
wait_until() { # wait_until <설명> <제한 초> <명령...>
  local what=$1 limit=$2; shift 2; local start=$SECONDS
  until "$@"; do
    (( SECONDS - start < limit )) || { echo "$what: ${limit}초 안에 끝나지 않았습니다" >&2; return 1; }
    sleep 10
  done
}
reset() { # 이전 패턴의 scaler와 부하를 지우고 podinfo를 replica <n>, 워크로드 노드를 <n>대 이하로 맞춥니다.
  k -n demo delete scaledobject podinfo --ignore-not-found >/dev/null
  k -n demo delete triggerauthentication azure-wi --ignore-not-found >/dev/null
  k -n demo delete interceptorroute podinfo --ignore-not-found >/dev/null 2>&1 || true
  k -n demo delete job k6 --ignore-not-found --wait >/dev/null
  k -n demo scale deploy podinfo --replicas "$1" >/dev/null
  log "워크로드 노드가 $1대 이하가 될 때까지 대기(NAP consolidation)"
  wait_until "노드 축소" 1800 bash -c "(( \$(kubectl --context $CTX get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l) <= $1 ))"
}
ready_scaledobject() { k -n demo wait scaledobject/podinfo --for=condition=Ready --timeout=5m >/dev/null; }
apply_http_scaler() { # apply_http_scaler <minReplicaCount>
  sed "s/minReplicaCount: 0/minReplicaCount: $1/" http-add-on/scaling.yaml | kapply
  ready_scaledobject
}
run_load() { # run_load <결과 이름> <TARGET_URL> [Host 헤더]
  local name=$1 target=$2 host=${3:-}
  # 기록은 클러스터 안의 watcher Job이 합니다. 로컬 네트워크가 끊겨도 간격이 유지됩니다.
  k -n demo delete job watcher --ignore-not-found --wait >/dev/null
  k -n demo create configmap watch-script --from-file=load/watch-replicas.sh --dry-run=client -o yaml | kapply
  sed "s|value: \"1200\"|value: \"${DURATION:-1200}\"|" load/watcher.yaml | kapply
  # watcher가 첫 기록을 남긴 뒤 부하를 시작합니다(이미지 준비 시간만큼 기록이 늦게 시작되는 것을 막음).
  wait_until "watcher 시작" 300 bash -c "kubectl --context $CTX -n demo logs job/watcher 2>/dev/null | grep -qE '^[0-9]+,'"
  sed -e "s|value: http://podinfo.demo.svc/|value: $target|" -e "s|value: \"\"|value: \"$host\"|" load/k6-job.yaml | kapply
  log "$name: k6 부하 시작(6분 30초), replica·노드 기록 ${DURATION:-1200}초"
  wait_until "k6 시작" 300 bash -c "[[ -n \$(kubectl --context $CTX -n demo get pod -l job-name=k6 -o jsonpath='{.items[0].status.containerStatuses[0].state.*.startedAt}' 2>/dev/null) ]]"
  local started k6_start
  started=$(k -n demo get pod -l job-name=k6 -o jsonpath='{.items[0].status.containerStatuses[0].state.*.startedAt}')
  k6_start=$(python3 -c "import datetime,sys;print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))" "$started")
  wait_until "k6 종료" 1200 bash -c "kubectl --context $CTX -n demo wait job/k6 --for=condition=complete --timeout=30s >/dev/null 2>&1"
  kto "$OUT/$name-k6.txt" -n demo logs job/k6
  wait_until "watcher 종료" $(( ${DURATION:-1200} + 300 )) bash -c "kubectl --context $CTX -n demo wait job/watcher --for=condition=complete --timeout=30s >/dev/null 2>&1"
  # epoch를 k6 컨테이너 시작 시각 기준 경과 초로 바꿉니다. 음수는 부하 전 기록입니다.
  kto "$OUT/$name.raw" -n demo logs job/watcher
  awk -F, -v t0="$k6_start" 'BEGIN{OFS=","; print "elapsed_s,desired,ready,hpa_metric,user_nodes"} /^[0-9]+,/{$1=$1-t0; print}' "$OUT/$name.raw" > "$OUT/$name.csv"
}
pattern_prometheus_rps() {
  reset 1
  sed -e "s|<keda-client-id>|$KEDA_CLIENT_ID|" -e "s|<amw-query-endpoint>|$AMW_QUERY_ENDPOINT|" prometheus/scaledobject.yaml | kapply
  ready_scaledobject
  run_load prometheus-rps http://podinfo.demo.svc/
}
pattern_http_add_on_min1() { reset 1; apply_http_scaler 1; run_load http-add-on-min1 "$INTERCEPTOR" "$HOST"; }
pattern_http_add_on_min0() {
  reset 1; apply_http_scaler 0
  # Pod와 워크로드 노드가 모두 사라져 첫 요청에 새 노드가 필요한 상태에서 시작합니다.
  log "replica 0, Pod 0개, 워크로드 노드 0대 대기"
  wait_until "replica 0" 900 bash -c "[[ \$(kubectl --context $CTX -n demo get deploy podinfo -o jsonpath='{.status.replicas}') =~ ^0?$ ]] && [[ -z \$(kubectl --context $CTX -n demo get pods -l app=podinfo --no-headers 2>/dev/null) ]]"
  wait_until "워크로드 노드 0" 1800 bash -c "(( \$(kubectl --context $CTX get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l) == 0 ))"
  run_load http-add-on-min0 "$INTERCEPTOR" "$HOST"
}
cold_request() { # cold_request <run 이름>: 0개 상태에서 첫 요청과 직후 warm 요청을 시스템 노드의 임시 Pod에서 보냅니다.
  wait_until "replica 0" 900 bash -c "[[ \$(kubectl --context $CTX -n demo get deploy podinfo -o jsonpath='{.status.replicas}') =~ ^0?$ ]]"
  local before; before=$(user_nodes)
  local r; r=$(kubectl --context "$CTX" run "coldstart-$RANDOM" --rm -i --restart=Never --image=curlimages/curl:8.23.0 --quiet \
    --overrides='{"spec":{"nodeSelector":{"kubernetes.azure.com/mode":"system"},"tolerations":[{"key":"CriticalAddonsOnly","operator":"Exists"}]}}' \
    -- sh -c "h=\$(curl -s -o /dev/null -D - -m 300 -w 'code=%{http_code} total=%{time_total}' -H 'Host: $HOST' $INTERCEPTOR | tr -d '\r' | grep -i -E 'x-keda-http-cold-start|code=' | tr '\n' ' ');
              w=\$(curl -s -o /dev/null -w '%{time_total}' -H 'Host: $HOST' $INTERCEPTOR); echo \"\$h warm_after=\$w\"")
  echo "run=$1 user_nodes_before=$before $r" | tee -a "$OUT/http-add-on-cold-start.txt"
}
pattern_http_add_on_cold_start() {
  reset 1; apply_http_scaler 0
  # 기존 노드에 자리가 있는 경우: 작은 keeper Pod로 워크로드 노드 1대를 유지합니다.
  k -n demo create deployment keeper --image=registry.k8s.io/pause:3.10 --dry-run=client -o yaml |
    kapply
  k -n demo set resources deploy keeper --requests=cpu=100m,memory=64Mi >/dev/null
  k -n demo rollout status deploy keeper --timeout=10m >/dev/null
  for r in 1 2 3; do cold_request "$r"; done
  # 새 노드가 필요한 경우: keeper를 지우고 워크로드 노드가 0대가 된 뒤 요청합니다.
  k -n demo delete deploy keeper >/dev/null
  wait_until "replica 0" 900 bash -c "[[ \$(kubectl --context $CTX -n demo get deploy podinfo -o jsonpath='{.spec.replicas}') == 0 ]]"
  wait_until "워크로드 노드 0" 1800 bash -c "(( \$(kubectl --context $CTX get nodes -l kubernetes.azure.com/mode=user --no-headers 2>/dev/null | wc -l) == 0 ))"
  cold_request node-cold
}
pattern_azure_monitor_agc() {
  reset 1
  local mc sub tenant alb addr
  mc=$(az aks show -g "$AZURE_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --query nodeResourceGroup -o tsv)
  sub=$(az account show --query id -o tsv); tenant=$(az account show --query tenantId -o tsv)
  alb=$(az resource list -g "$mc" --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[0].name" -o tsv)
  sed -e "s|<keda-client-id>|$KEDA_CLIENT_ID|" -e "s|<alb-resource-name>|$alb|" -e "s|<node-resource-group>|$mc|" \
      -e "s|<subscription-id>|$sub|" -e "s|<tenant-id>|$tenant|" agc/scaledobject.yaml | kapply
  ready_scaledobject
  addr=$(k -n demo get gateway web -o jsonpath='{.status.addresses[0].value}')
  # 서브넷 NSG는 클러스터 생성 뒤에 연결될 수 있으므로(구독 정책 등) 부하 직전에 다시 확인하고
  # 클러스터 안에서 frontend가 응답할 때까지 기다립니다.
  ./agc/allow-frontend.sh
  log "AGC frontend 응답 대기"
  wait_until "AGC frontend 응답" 600 bash -c "kubectl --context $CTX -n demo run agc-check-\$RANDOM --rm -i --restart=Never --quiet \
    --image=curlimages/curl:8.23.0 --pod-running-timeout=2m \
    --overrides='{\"spec\":{\"nodeSelector\":{\"kubernetes.azure.com/mode\":\"system\"},\"tolerations\":[{\"key\":\"CriticalAddonsOnly\",\"operator\":\"Exists\"}]}}' \
    -- curl -s -o /dev/null -m 5 -w '%{http_code}' http://$addr/ 2>/dev/null | grep -q 200"
  run_load azure-monitor-agc "http://$addr/"
}

list=${PATTERN:-}
# azd up도 이 hook을 실행하므로 값이 없으면 안내만 하고 끝냅니다.
[[ -n $list ]] || { echo "실행할 실험이 없습니다. 예: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"; exit 0; }
for p in ${list//,/ }; do
  fn=pattern_${p//-/_}
  declare -F "$fn" >/dev/null || { echo "알 수 없는 패턴: $p" >&2; exit 1; }
  log "패턴 $p 시작"; "$fn"; log "패턴 $p 완료"
done
reset 1
echo "결과: $OUT"
