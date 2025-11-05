aks 에서 pod의 부하 상황을 분석할 때 file write 지연으로 인한 병목 현상을 발견한 상황 소개

1. 특정 시점부터 응답속도가 현저히 느려지는 현상(5ms 이내 -> 1분 이상) 확인   
1분 지연은 cosmosdb client connection timeout 이후 retry 등 정책으로 재시도된 것으로 파악.
그러나 이 지연이 cosmos query 응답속도는 아니기 때문에 추가적인 분석 필요
<img width="1336" height="390" alt="image" src="https://github.com/user-attachments/assets/55ec4215-4338-4b2d-8614-235510dbdc50" />
3. 부하량이 증가할 수록 메모리가 지속적으로 증가하는 추세 확인
4. 특정 시점 이후 gc가 발생하나 연이어서 메모리가 다시 full 되는 현상
<img width="1192" height="669" alt="스크린샷 2025-11-05 184653" src="https://github.com/user-attachments/assets/fe0d2b13-156c-48bf-8daa-af51450282bc" />
5. trace 정보에서 profile을 확인했을 때 별다른 stack trace가 보이지 않고 아래에 수많은 file system async activiity 확인
<img width="1156" height="741" alt="image" src="https://github.com/user-attachments/assets/556786e8-afbb-4602-a657-298f2fb889a9" />

aks -> nfs write 지연 이슈로 의심 -> nfs capacity 증설
증설 이후 memory도 안정화되고 응답속도도 정상으로 돌아옴
