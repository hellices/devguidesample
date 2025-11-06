환경
- aks
- 300 pod
- nodejs 컨테이너
- netapp files pv
- pod는 http request를 받아서 async pool로 file 쓰기를 넘기고 200 ok 응답을 주고 있음

트래픽 증가 상황에서 cpu가 급격히 치는 현상 발생
<img width="568" height="251" alt="image" src="https://github.com/user-attachments/assets/7e916a87-7199-4082-be02-19158c255bf6" />

netapp files는 안정적으로 read/write하는 것으로 확인(./file_io_throttling.md 이후)

network io의 특이점과 disk write가 되는(nfs service임에도) 특이 현상 확인
<img width="1761" height="672" alt="image" src="https://github.com/user-attachments/assets/50805dd4-9b9b-440f-8fc2-e964ff8bfea1" />

해당 node의 system.io.w_await 매트릭을 확인했을 때 특정 시점에 wait 현상 발생 확인
<img width="1728" height="615" alt="image" src="https://github.com/user-attachments/assets/52ccc592-f83f-454d-9041-6458fe4fc3bc" />

관련 pod의 상태를 분석한 결과 file system 대기가 급격히 증가
<img width="1760" height="1284" alt="image" src="https://github.com/user-attachments/assets/31c9275d-0956-4c32-8f58-bece91714154" />

현 상태에서 nfs(netapp files) csi driver 설치 시 필요한 옵션을 검토
client의 pool(nfs)이 부족한 것을 의심하고 있음
