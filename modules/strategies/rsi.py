import sys
import datetime

import pandas as pd


async def calculate_rsi_date(queue_dict, to_rsi_manage_id, to_upbit_api_manage_id, trade_manage_id):
    try:
        td_by_code = {}
        rsi_count = 14
        while True:
            data = await queue_dict[to_rsi_manage_id].get()

            code = data['code']

            if code == '시뮬레이션요청':
                response_id = data['response_id']
                db_data = data['data']

                df = pd.DataFrame(db_data)
                ohlc = df[5]
                rsi_list = get_all_rsi(ohlc, rsi_count)

                queue_dict[response_id].put_nowait({
                    'code': code, 'RSI목록': rsi_list
                })
                continue

            date_time = data['date_time']
            ohlc = data['ohlc']

            # 이번에 처음 code 계산을 처리하는 경우에는 지금까지의 정보를 REST API로 가져온다.
            if code not in td_by_code.keys():
                my_datetime_format = '%Y%m%d-%H%M'
                upbit_datetime_format = '%Y-%m-%d %H:%M:%S'
                target_date_time = datetime.datetime.strftime(
                    datetime.datetime.strptime(date_time, my_datetime_format) - datetime.timedelta(minutes=1),
                    upbit_datetime_format)

                queue_dict[to_upbit_api_manage_id].put_nowait({
                    'code': '분봉데이터조회', 'response_id': to_rsi_manage_id, 'market': code,
                    'target_time': target_date_time
                })
                min_data = await queue_dict[to_rsi_manage_id].get()

                df = min_data["분봉데이터"]
                df = pd.DataFrame(df)
                df = df.reindex(index=df.index[::-1]).reset_index()

                td_by_code[code] = df["trade_price"]

            # 새로운 ohlc 가 들어온 경우에 가장 먼저 들어온 ohlc 를 지우고 넣는다 (FIFO)
            td_by_code[code] = td_by_code[code].drop(0)
            td_by_code[code] = td_by_code[code].append(pd.DataFrame(data=[[ohlc[-1]]]).iloc[-1]).reset_index(drop=True)

            # RSI 계산 진행 (종가 간 차이 계산)
            rsi = get_rsi(td_by_code[code], rsi_count)

            queue_dict[trade_manage_id].put_nowait({'code': code, 'rsi': rsi})

    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        print(exc_tb.tb_lineno)
        print(e)
        pass


def get_all_rsi(ohlc, period):
    delta = ohlc.diff()
    gains, declines = delta.copy(), delta.copy()
    gains[gains < 0] = 0
    declines[declines > 0] = 0

    _gain = gains.ewm(com=(period - 1), min_periods=period).mean()
    _loss = declines.abs().ewm(com=(period - 1), min_periods=period).mean()

    rs = _gain / _loss

    return 100 - (100 / (1+rs))


def get_rsi(ohlc, period):
    return get_all_rsi(ohlc, period).iloc[-1]


async def auto_trade_with_rsi(rsi_by_code, rsi_level_by_code, lower_rsi, upper_rsi, market, rsi):
    rsi_by_code[market] = rsi
    print(f'{datetime.datetime.now()}:{market}: {rsi}')

    if market in rsi_level_by_code.keys():
        old_rsi_level = rsi_level_by_code[market]
        cur_rsi_level = old_rsi_level

        if rsi < lower_rsi:
            cur_rsi_level = 0
        elif lower_rsi < rsi < upper_rsi:
            cur_rsi_level = 1
        elif upper_rsi < rsi:
            cur_rsi_level = 2

        rsi_level_by_code[market] = cur_rsi_level

        if old_rsi_level > cur_rsi_level:  # rsi 기준선 하향 돌파
            if cur_rsi_level == 0:  # lower_rsi 하향 돌파
                pass
            elif cur_rsi_level == 1:  # upper_rsi 하향 돌파 -> 매도
                print(f'{market}, rsi 하향돌파 -> 매도 진행')
                return '매도'
        elif old_rsi_level < cur_rsi_level:  # rsi 기준선 상향 돌파
            if cur_rsi_level == 1:  # lower_rsi 상향 돌파 -> 매수
                print(f'{market}, rsi 상향돌파 -> 매수 진행')
                return '매수'
            elif cur_rsi_level == 2:  # upper_rsi 상향 돌파
                pass
    else:
        cur_rsi_level = None

        if rsi < lower_rsi:
            cur_rsi_level = 0
        elif lower_rsi < rsi < upper_rsi:
            cur_rsi_level = 1
        elif upper_rsi < rsi:
            cur_rsi_level = 2

        if cur_rsi_level is not None:
            rsi_level_by_code[market] = cur_rsi_level
