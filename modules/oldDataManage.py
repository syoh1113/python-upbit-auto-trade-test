import datetime
import pytz

import aiosqlite
from aiofile import async_open


async def save_old_minute_price(queue_dict, to_save_old_minute_price_id, to_upbit_api_manage_id, to_db_manage_id):
    # 시장 코드를 가져온다
    queue_dict[to_db_manage_id].put_nowait({
        'code': '시장코드조회',
        'response_id': to_save_old_minute_price_id
    })
    data = await queue_dict[to_save_old_minute_price_id].get()

    row = data['시장코드목록']
    for r in row:
        market = r[0]

        if market[0:3] != 'KRW':
            continue

        # db 갱신 시간 요청
        queue_dict[to_db_manage_id].put_nowait({
            'code': 'update_date_table 갱신시간 요청',
            'response_id': to_save_old_minute_price_id,
            'market': market
        })
        data = await queue_dict[to_save_old_minute_price_id].get()

        max_date, min_date = data['max_date'], data['min_date']

        db_format_time = "%Y-%m-%d %H:%M"

        today = datetime.datetime.now()
        today_s = datetime.datetime.strftime(today, db_format_time)
        today = datetime.datetime.strptime(today_s, db_format_time)

        while True:
            # 가져와야 하는 시간대 계산
            target_time = ''

            # db에 처음 저장하는 경우 -> 현재 시간부터 시작해서 db 저장을 시작한다.
            if max_date == '0' and min_date == '0':
                pass

            # 아직 과거까지의 데이터를 저장안했을때
            elif min_date != '-1':
                # 과거 업비트 요청해야 함
                target_time = datetime.datetime.strftime(
                    datetime.datetime.strptime(min_date, db_format_time) + datetime.timedelta(hours=-9), db_format_time)

            # 과거 데이터 저장은 끝났으나, 아직 현재 시간(-10분)에 대한 정보가 없을 경우 -> max_date + 3시간 값부터 시작해서 db 저장을 시작한다.
            elif datetime.datetime.strptime(max_date, db_format_time) + datetime.timedelta(minutes=10) < today:
                target_time = datetime.datetime.strftime(
                    datetime.datetime.strptime(max_date, db_format_time) +
                    datetime.timedelta(hours=3 - 9), db_format_time
                )
            else:  # 요청할 데이터 없음
                break

            # 업비트 요청
            queue_dict[to_upbit_api_manage_id].put_nowait({
                'code': '분봉데이터조회',
                'response_id': to_save_old_minute_price_id,
                'market': market,
                'target_time': target_time
            })
            data = await queue_dict[to_save_old_minute_price_id].get()

            # db 분봉데이터 저장 요청
            queue_dict[to_db_manage_id].put_nowait({
                'code': '과거분봉데이터저장',
                'response_id': to_save_old_minute_price_id,
                'market': market,
                'min_date': min_date,
                'max_date': max_date,
                'data': data['분봉데이터']
            })
            data = await queue_dict[to_save_old_minute_price_id].get()
            min_date, max_date = data['min_date'], data['max_date']

            print(f'현재 마켓 = {market}, 현재까지한시간 = {min_date} ~ {max_date}')


async def save_old_data_with_strategy(queue_dict, to_analyze_old_data_with_strategy_id, to_db_manage_id,
                                      to_do_auto_trade):
    # 종목 리스트 가져오기
    queue_dict[to_db_manage_id].put_nowait({'code': '시장코드조회', 'response_id': to_analyze_old_data_with_strategy_id})
    data = await queue_dict[to_analyze_old_data_with_strategy_id].get()

    market_list = data['시장코드목록']

    # 각 종목별로 시뮬레이션 진행
    for market_tuple in market_list:
        market = market_tuple[0]

        if market[0:3] != 'KRW':
            continue

        # TODO: KRW-BCH table이 망가진거 같음, 삭제하고 다시 수집해야 할수도 있음 -> MySQL? MariaDB? 로 갈아타야 할듯..
        if market in ["KRW-ADA", "KRW-ADX", "KRW-AERGO", "KRW-AHT", "KRW-ANKR", "KRW-AQT", "KRW-ARDR", "KRW-ARK", "KRW-ATOM", "KRW-AXS", "KRW-BAT"]:
            continue

        # 시뮬레이션 계산 속도 측정
        start = datetime.datetime.now()

        # 분봉 데이터 요청하기
        queue_dict[to_db_manage_id].put_nowait({
            'code': '총분봉데이터요청', 'response_id': to_analyze_old_data_with_strategy_id, 'market': market})
        data = await queue_dict[to_analyze_old_data_with_strategy_id].get()

        # rsi 가져오면서 매수/매도 시뮬레이션 진행 - 수익률 계산
        data = data['총분봉데이터']

        strategies = ['RSI']
        queue_dict[to_do_auto_trade].put_nowait({
            'code': '시뮬레이션보조지표저장요청', 'response_id': to_analyze_old_data_with_strategy_id, 'data': data,
            'strategies': strategies, 'market': market
        })
        results = await queue_dict[to_analyze_old_data_with_strategy_id].get()

        queue_dict[to_db_manage_id].put_nowait({
            'code': '시뮬레이션보조지표저장요청', 'response_id': to_analyze_old_data_with_strategy_id, 'data': data,
            'results': results, 'market': market
        })
        await queue_dict[to_analyze_old_data_with_strategy_id].get()

        print(f'종목 {market}에 대해 걸린 보조 지표 저장 시간 = {datetime.datetime.now() - start}')


async def analyze_old_data_with_strategy(queue_dict, to_analyze_old_data_with_strategy_id, to_db_manage_id,
                                         to_do_auto_trade):
    # 종목 리스트 가져오기
    queue_dict[to_db_manage_id].put_nowait({'code': '시장코드조회', 'response_id': to_analyze_old_data_with_strategy_id})
    data = await queue_dict[to_analyze_old_data_with_strategy_id].get()

    market_list = data['시장코드목록']

    # 각 종목별로 시뮬레이션 진행
    for market_tuple in market_list:
        market = market_tuple[0]

        if market[0:3] != 'KRW':
            continue

        # 시뮬레이션 계산 속도 측정
        start = datetime.datetime.now()

        # 분봉 데이터 요청하기
        queue_dict[to_db_manage_id].put_nowait({
            'code': '총분봉데이터요청', 'response_id': to_analyze_old_data_with_strategy_id, 'market': market})
        data = await queue_dict[to_analyze_old_data_with_strategy_id].get()

        # rsi 가져오면서 매수/매도 시뮬레이션 진행 - 수익률 계산
        data = data['총분봉데이터']

        queue_dict[to_do_auto_trade].put_nowait({
            'code': '시뮬레이션요청', 'response_id': to_analyze_old_data_with_strategy_id, 'data': data,
            'strategies': ['RSI'], 'market': market, 'save_db': True
        })
        result = await queue_dict[to_analyze_old_data_with_strategy_id].get()

        result = result['result']
        for k in result.keys():
            if k == 'RSI':
                result_k = result[k]

                async with async_open(f"./testlogs/rsi_backtest/30_70/{market}.csv", 'a') as afp:
                    await afp.write(f"매수시점, 매수시가, 매수고가, 매수저가, 매수종가, 매도시점, 매도시가, 매도고가, 매도저가, 매도종가")

                for r in result_k:
                    buy_info, sell_info = r['매수정보'], r['매도정보']
                    buy_time, buy_o, buy_h, buy_l, buy_c = buy_info
                    sell_time, sell_o, sell_h, sell_l, sell_c = sell_info

                    async with async_open(f"./testlogs/rsi_backtest/30_70/{market}.csv", 'a') as afp:
                        await afp.write(f"{buy_time}, {buy_o}, {buy_h}, {buy_l}, {buy_c}, "
                                        f"{sell_time}, {sell_o}, {sell_h}, {sell_l}, {sell_c}\n")

        print(f'종목 {market}에 대해 걸린 시뮬레이션 시간 = {datetime.datetime.now() - start}')
