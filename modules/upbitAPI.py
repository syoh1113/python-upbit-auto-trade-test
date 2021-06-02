import datetime
import json

import asyncio
import sys

import aiohttp
import websockets

import jwt
import uuid
import hashlib
from urllib.parse import urlencode


async def get_real_data_manage(queue_dict, with_db_manage_id, to_process_real_data_id, program_setting):
    try:
        get_real_data_from_ws, get_orderbook_from_ws \
            = program_setting["get_trade_from_ws"], program_setting["get_orderbook_from_ws"]

        to_db_manage_id, from_db_manage_id = with_db_manage_id

        queue_dict[to_db_manage_id].put_nowait({
            'code': '시장코드조회',
            'response_id': from_db_manage_id,
        })
        data = await queue_dict[from_db_manage_id].get()

        market_list = data['시장코드목록']

        # db 로부터 모든 코드 가져오기
        krw_codes = []
        for r in market_list:
            if r[0][:3] != 'KRW':
                continue
            krw_codes.append(r[0])

        uri = "wss://api.upbit.com/websocket/v1"
        while True:
            try:
                async with websockets.connect(uri, ping_interval=20) as ws:
                    subscribe_fmt = [{"ticket": "test"}]
                    if get_real_data_from_ws:
                        subscribe_fmt.append({"type": "trade", "codes": krw_codes, "isOnlyRealtime": True})
                    if get_orderbook_from_ws:
                        subscribe_fmt.append({"type": "orderbook", "codes": krw_codes, "isOnlyRealtime": True})
                    subscribe_fmt.append({"format": "SIMPLE"})

                    subscribe_data = json.dumps(subscribe_fmt)
                    await ws.send(subscribe_data)

                    while True:
                        data = await ws.recv()
                        queue_dict[to_process_real_data_id].put_nowait(json.loads(data))

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(exc_tb.tb_lineno)
                print(datetime.datetime.now())
                print(str(e))
                await asyncio.sleep(10)
                continue

    except Exception as e:
        print(e)
        pass


async def upbit_api_manage(queue_dict, upbit_api_manage_id, upbit_setting):
    account_info = {}
    krw_market = "KRW-KRW"

    try:
        while True:
            data = await queue_dict[upbit_api_manage_id].get()

            # 남은 요청 횟수 초기화
            min_remains = 100
            sec_remains = 100

            code = data['code']
            response_id = data['response_id']

            if code == '주문':
                market = data['market']
                side = data['side']
                ord_type = data['ord_type']
                price = None
                volume = None
                if ord_type == 'price':
                    price = data['price']
                elif ord_type == 'market':
                    volume = data['volume']
                min_remains, sec_remains = await trade_coin_with_rest_api(upbit_setting, market, side, ord_type,
                                                                          price=price, volume=volume)
                if market in account_info.keys():
                    account_info[market]["can_be_modified"] = True
                account_info[krw_market]["can_be_modified"] = True
                queue_dict[response_id].put_nowait({'code': code, 'market': market, 'ord_type': ord_type})

            elif code == '전체계좌조회':
                min_remains, sec_remains, account_info = await get_coin_volume(upbit_setting)
                queue_dict[response_id].put_nowait({'code': code, 'account_info': account_info})

            elif code == '코인보유수량확인':
                market = data['market']
                if market not in account_info.keys() or account_info[market]["can_be_modified"]:
                    min_remains, sec_remains, account_info = await get_coin_volume(upbit_setting)
                if market not in account_info.keys():
                    queue_dict[response_id].put_nowait({'code': code, 'market': market, 'volume': '0.0'})
                else:
                    queue_dict[response_id].put_nowait({'code': code,
                                                        'market': market, 'volume': account_info[market]["balance"]})

            elif code == '시장코드조회':
                min_remains, sec_remains, market_list = await get_market_codes(upbit_setting["SERVER_URL"])
                queue_dict[response_id].put_nowait({'code': code, '시장코드목록': market_list})

            elif code == '분봉데이터조회':
                market, target_time = data['market'], data['target_time']
                min_remains, sec_remains, minutes = await get_minute_data(
                    market, target_time, upbit_setting["SERVER_URL"]
                )
                queue_dict[response_id].put_nowait({'code': code, '분봉데이터': minutes})

            # 현재 남은 요청횟수가 10번 또는 2번 아래이면 대기 (2분, 2초)
            if min_remains < 10:
                await asyncio.sleep(120)
            elif sec_remains < 2:
                await asyncio.sleep(2)

    except Exception as e:
        print(e)
        pass


def get_min_sec_remains(header):
    split = str(header).split(';')

    results = []
    for i in range(1, len(split)):
        results.append(int(split[i].split("=")[1]))
    return results


# 참고: https://docs.upbit.com/reference#%EC%A3%BC%EB%AC%B8%ED%95%98%EA%B8%B0
async def trade_coin_with_rest_api(upbit_setting, market, side, ord_type, price=None, volume=None):
    access_key = upbit_setting["ACCESS_KEY"]
    secret_key = upbit_setting["SECRET_KEY"]
    server_url = upbit_setting["SERVER_URL"]

    query = {
        'market': market,
        'side': side,
        'ord_type': ord_type,
    }
    if price is not None:
        query['price'] = price
    if volume is not None:
        query['volume'] = volume
    query_string = urlencode(query).encode()

    m = hashlib.sha512()
    m.update(query_string)
    query_hash = m.hexdigest()

    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
        'query_hash': query_hash,
        'query_hash_alg': 'SHA512',
    }

    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    async with aiohttp.ClientSession() as session:
        async with session.post(server_url + "/v1/orders", headers=headers, params=query) as response:
            header = response.headers['Remaining-Req']
            min_remains, sec_remains = get_min_sec_remains(header)

            responses = await response.json()

            return min_remains, sec_remains


# 참고: https://docs.upbit.com/reference#%EC%A3%BC%EB%AC%B8-%EA%B0%80%EB%8A%A5-%EC%A0%95%EB%B3%B4
async def get_coin_volume(upbit_setting):
    access_key = upbit_setting["ACCESS_KEY"]
    secret_key = upbit_setting["SECRET_KEY"]
    server_url = upbit_setting["SERVER_URL"]

    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
    }

    jwt_token = jwt.encode(payload, secret_key)
    authorize_token = 'Bearer {}'.format(jwt_token)
    headers = {"Authorization": authorize_token}

    account_info = {}

    async with aiohttp.ClientSession() as session:
        async with session.get(server_url + "/v1/accounts", headers=headers) as response:
            header = response.headers['Remaining-Req']
            min_remains, sec_remains = get_min_sec_remains(header)

            responses = await response.json()

            for res in responses:
                currency = res["unit_currency"] + "-" + res["currency"]
                account_info[currency] = {}

                balance = res["balance"]
                account_info[currency]["balance"] = balance

                locked = res["locked"]
                account_info[currency]["locked"] = locked

                avg_buy_price = res["avg_buy_price"]
                account_info[currency]["avg_buy_price"] = avg_buy_price

                avg_buy_price_modified = res["avg_buy_price_modified"]
                account_info[currency]["avg_buy_price_modified"] = avg_buy_price_modified

                unit_currency = res["unit_currency"]
                account_info[currency]["unit_currency"] = unit_currency

                account_info[currency]["can_be_modified"] = False

            return min_remains, sec_remains, account_info


async def get_market_codes(server_url):
    url = server_url + "/v1/market/all"
    querystring = {"isDetails": "false"}
    headers = {"Accept": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=querystring) as response:
            res_json = await response.json()
            min_remains, sec_remains = get_min_sec_remains(response.headers['Remaining-Req'])
            return min_remains, sec_remains, res_json


async def get_minute_data(market, target_time, server_url):
    url = server_url + "/v1/candles/minutes/1"
    querystring = {"market": market, "count": "200"}
    if target_time != '':
        querystring["to"] = target_time + ":01"
    headers = {"Accept": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=querystring) as response:
            res_json = await response.json()
            min_remains, sec_remains = get_min_sec_remains(response.headers['Remaining-Req'])
            return min_remains, sec_remains, res_json
