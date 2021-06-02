# 개요
UPBIT API를 이용하여 자동 매매 관련 기능들을 구현한 python 프로그램입니다.
현재는 RSI 보조 지표를 이용하여 30~70 구간에서 매매를 수행합니다.
해당 프로그램을 실행하여 실제 자동 매매를 수행하기 위해서는 코드 내 몇몇 수정이 필요합니다. (주의사항 참고)

# 제공하고 있는 기능들
1. REST API를 통해 UPBIT 내 KRW 시장 내 코인들의 분봉 데이터들을 DB에 저장합니다.
2. 웹소켓을 통해 코인들의 실시간 호가창 및 체결가 데이터를 가져옵니다.
3. 실시간으로 RSI 보조 지표를 계산합니다.
4. 계산된 RSI 보조 지표 값을 통해 자동 매매를 수행합니다.

# 실행방법
1. setting.json 파일 내 ACCESS_KEY, SECRET_KEY 값에 UPBIT 키 값을 기입합니다.
2. modules 폴더 내 asyncMain.py 파일 내 program_setting 사전 변수 값을 활성하고자 하는 기능에 맞춰 바꿔줘야 합니다.

# 실행결과
1. 아래 그림과 같이 각 종목들의 분봉데이터를 DB에 저장합니다. (RSI 보조 지표 또한 관련 비동기 태스크에 의해 추가적으로 계산되어 저장될 수 있습니다.)
![image](https://user-images.githubusercontent.com/46051622/120479602-14482200-c3e9-11eb-9fce-6895ca6e14e6.png)

2. RSI 보조 지표를 참고하여 아래와 같이 실시간 매매를 수행합니다. (테스트기간: 2021.05.30 03:55 ~ 2021.05.30 14:03, 총손익: -4,000원)
![image](https://user-images.githubusercontent.com/46051622/120479985-87ea2f00-c3e9-11eb-8b99-6b9d958b779d.png)


# 주의사항
- 현재 github 에 push 한 버전은 직접 실행하지 않은 코드입니다. 가능하면 코드 내용들을 숙지한 후 직접 수정하여 사용하는 것을 권합니다.
   - 자동 매매 기능을 수행하기 위해서는 modules/asyncMain.py 내 process_real_data_manage 함수 코드 일부를 수정해야 합니다. 178번 줄에 continue 구문에 의해 해당 구문 아래 코드들이 실행되지 않고 있으나, 해당 코드들은 웹소켓으로부터 수신된 실시간 체결데이터를 통해 실시간으로 분봉 데이터를 생성하는 코드입니다. RSI 보조 지표의 실시간 계산을 위해서는 해당 코드의 활성화가 필요하기 때문에 continue 구문을 삭제해야 합니다.

# 비동기 태스크 개요도
해당 프로그램은 여러 비동기 태스크들이 큐를 통해 서로 데이터를 주고 받는 구조입니다.
아래 그림은 각 비동기 태스크들의 관계를 표현하고 있습니다.
![image](https://user-images.githubusercontent.com/46051622/120487345-d8b15600-c3f0-11eb-84c6-f00cae46c75b.png)

# 코드 파일 설명
- main.py: main 프로그램 코드
   - PyQT UI를 띄웁니다. 현재 UI는 아무런 기능도 수행하지 않습니다. (같은 위치 내 ui 폴더 내 관련 파일들이 있습니다.)
   - modules 폴더 내 asyncMain.py 에 정의되어있는 RealDataGetter 이름의 QThread를 실행합니다.
- modules/asyncMain.py: 여러 비동기 태스크들을 실행하는 프로그램 코드
   - RealDataGetter 이름의 QThread 가 정의되어 있습니다. 해당 QThread는 같은 파일 내 async_run 함수를 실행합니다.
   - async_run 함수는 내부에 정의되어 있는 program_setting 사전 변수 내 값을 통해 관련 기능들이 구현된 비동기 태스크들을 실행합니다. 사용자는 해당 사전 변수 값을 수정하여 필요한 비동기 태스크들을 활성화/비활성화 시킬 수 있습니다.
   - process_real_data_manage 함수는 웹소켓으로부터 수신된 실시간 체결/호가창 데이터를 처리합니다. 현재는 DB 비동기 태스크에 저장 요청을 보내거나, RSI 보조 지표를 계산하는 비동기 태스크에 실시간 분봉 데이터를 계산하여 전달합니다.
- modules/dbManage.py: SQLite DB를 관리하는 비동기 태스크입니다.
- modules/oldDataManage.py: DB에 저장된 과거 종목별 분봉 데이터를 통해 보조 지표를 미리 계산하는 기능을 가지고 있습니다.
- modules/trade.py: 실제 매매 요청을 처리하는 기능을 가지고 있습니다.
- modules/truncated.py: 현재는 사용되지 않는 함수들을 모아놓고 있습니다.
- modules/upbitAPI.py: UPBIT REST API 요청들을 처리하는 기능을 가지고 있습니다.
- modules/strategies/rsi.py: RSI 보조 지표를 계산하는 기능을 가지고 있습니다.

# 추후 계획
1. 해당 코드들은 여러 비동기 태스크들이 큐를 통해 각자 필요한 데이터들을 주고 받는 형식입니다. 개발 초기 단계에서 의도한 바와 달리 현재는 상당히 복잡한 구조를 가지게 되었습니다. 해당 구조 위에서 기능들을 계속 추가하기에는 개발 비용이 많이 필요할 것으로 예상되어 현재 Golang 언어로 다시 리팩토링을 진행할 예정입니다.
2. SQLite DB를 사용하고 있으나 thread-safe 하지 않습니다. 추후 확장성을 위해 서버/클라이언트 기반의 SQL을 채택할 예정입니다.
