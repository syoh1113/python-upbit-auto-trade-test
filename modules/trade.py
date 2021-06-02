import math

from modules.strategies.rsi import *


async def get_krw_remains(queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id):
    queue_dict[to_upbit_api_manage_id].put_nowait({
        'response_id': from_upbit_api_manage_id,
        'code': "코인보유수량확인",
        'market': 'KRW-KRW'
    })
    data = await queue_dict[from_upbit_api_manage_id].get()
    return data['volume']


async def buy_coin_with_market_order(market, price, queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id):
    # 보유 원화 확인
    krw_remains = await get_krw_remains(queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id)
    if float(krw_remains) < float(price):
        return False

    queue_dict[to_upbit_api_manage_id].put_nowait({
        'response_id': from_upbit_api_manage_id,
        'code': '주문',
        'market': market,
        'side': 'bid',
        'ord_type': 'price',
        'price': price
    })
    data = await queue_dict[from_upbit_api_manage_id].get()
    return True


async def sell_coin_with_market_order(market, queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id):
    # 보유 수량 확인
    queue_dict[to_upbit_api_manage_id].put_nowait({
        'response_id': from_upbit_api_manage_id,
        'code': "코인보유수량확인",
        'market': market
    })
    data = await queue_dict[from_upbit_api_manage_id].get()
    volume = data['volume']

    # 매도 요청 전송
    queue_dict[to_upbit_api_manage_id].put_nowait({
        'response_id': from_upbit_api_manage_id,
        'code': '주문',
        'market': market,
        'side': 'ask',
        'ord_type': 'market',
        'volume': volume
    })
    data = await queue_dict[from_upbit_api_manage_id].get()


async def trading_manage(queue_dict, to_do_auto_trade, ids_with_upbit_api_manage, ids_with_strategy):

    unit_buy_price = '10000.0'

    try:
        from_upbit_api_manage_id, to_upbit_api_manage_id = ids_with_upbit_api_manage
        to_rsi_strategy = ids_with_strategy[0]

        # 전체 계좌 조회
        queue_dict[to_upbit_api_manage_id].put_nowait({
            'response_id': from_upbit_api_manage_id,
            'code': "전체계좌조회",
        })
        data = await queue_dict[from_upbit_api_manage_id].get()
        account_info = data["account_info"]

        # 현재 보유 코인 목록
        coin_list_i_have = []
        for c in account_info:
            if c == "KRW-KRW":
                continue
            coin_list_i_have.append(c)

        # RSI 전략 사용
        rsi_by_code = {}
        rsi_level_by_code = {}  # 0: ~ lower_rsi, 1: lower_rsi ~ upper_rsi, 2: upper_rsi ~
        lower_rsi = 30
        upper_rsi = 70

        while True:
            data = await queue_dict[to_do_auto_trade].get()
            code = data['code']

            if code == '시뮬레이션보조지표저장요청':
                response_id, raw_data, strategies = data['response_id'], data['data'], data['strategies']

                results = {}
                for s in strategies:
                    if s == 'RSI':
                        queue_dict[to_rsi_strategy].put_nowait({
                            'code': '시뮬레이션요청', 'response_id': to_do_auto_trade, 'data': raw_data
                        })
                        queue_result = await queue_dict[to_do_auto_trade].get()
                        rsi_list = queue_result['RSI목록']
                        results[s] = rsi_list

                queue_dict[response_id].put_nowait({'code': code, 'results': results})

            if code == '시뮬레이션요청':
                response_id, raw_data, strategies = data['response_id'], data['data'], data['strategies']

                results = {}
                for s in strategies:
                    if s == 'RSI':
                        queue_dict[to_rsi_strategy].put_nowait({
                            'code': '시뮬레이션요청', 'response_id': to_do_auto_trade, 'data': raw_data
                        })
                        queue_result = await queue_dict[to_do_auto_trade].get()
                        rsi_list = queue_result['RSI목록']

                        market = "simulation"
                        cur_transaction = {}
                        for i in range(len(rsi_list)):
                            rsi = rsi_list[i]

                            if math.isnan(rsi):
                                continue

                            result = await auto_trade_with_rsi(
                                rsi_by_code, rsi_level_by_code, lower_rsi, upper_rsi, market, rsi
                            )
                            if result == '매수':
                                if market not in coin_list_i_have:
                                    cur_transaction['매수정보'] = [
                                        raw_data[i][1], raw_data[i][2], raw_data[i][3], raw_data[i][4], raw_data[i][5]
                                    ]
                                    coin_list_i_have.append(market)
                            elif result == '매도':
                                if market in coin_list_i_have:
                                    cur_transaction['매도정보'] = [
                                        raw_data[i][1], raw_data[i][2], raw_data[i][3], raw_data[i][4], raw_data[i][5]
                                    ]
                                    coin_list_i_have.remove(market)
                                    if s not in results:
                                        results[s] = []
                                    results[s].append(cur_transaction)
                                    cur_transaction = []
                        rsi_by_code = {}
                        rsi_level_by_code = {}

                queue_dict[response_id].put_nowait({'code': code, 'result': results})

            elif code == 'RSI':
                market, rsi = data['market'], data['rsi']

                result = await auto_trade_with_rsi(rsi_by_code, rsi_level_by_code, lower_rsi, upper_rsi, market, rsi)

                if result == '매수':
                    if market not in coin_list_i_have:
                        ret = await buy_coin_with_market_order(
                            market, unit_buy_price, queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id)
                        if ret:
                            coin_list_i_have.append(market)

                elif result == '매도':
                    if market in coin_list_i_have:
                        await sell_coin_with_market_order(
                            market, queue_dict, to_upbit_api_manage_id, from_upbit_api_manage_id)
                        coin_list_i_have.remove(market)

    except Exception as e:
        print(e)
        pass
