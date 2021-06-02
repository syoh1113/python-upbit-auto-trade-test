import asyncio
import sys
import json

from PyQt5.QtCore import QThread
import time
import datetime
import aiosqlite

from modules.upbitAPI import *
from modules.dbManage import *
from modules.oldDataManage import *
from modules.trade import *

from modules.strategies.rsi import *


class RealDataGetter(QThread):
    def __init__(self, upbit_setting):
        super().__init__()
        self.upbit_setting = upbit_setting

    def run(self):
        asyncio.run(async_run(self.upbit_setting))


async def async_run(upbit_setting):
    program_setting = {
        'write_trade_orderbook_to_db': False,  # db 에 trade, orderbook 실시간 데이터 저장 여부
        'get_trade_from_ws': False,  # trade 실시간 데이터 수신 여부
        'get_orderbook_from_ws': False,  # orderbook 실시간 데이터 수신 여부
        'save_old_minute_price_to_db_with_rest_api': False,  # REST API 로 분봉 데이터 db 저장 여부
        'analyze_old_minute_price_with_strategy': True,  # 과거 분봉 데이터 기반 전략 분석 코드 실행 여부

        'get_rsi': True,  # RSI 계산 코드 실행 여부
    }

    if program_setting['analyze_old_minute_price_with_strategy'] or program_setting['get_rsi']:
        program_setting['do_auto_trade'] = True  # Auto-trade 실행 여부

    to_upbit_api_manage_id = "to_upbit_api_manage_id"
    to_db_manage_id = "to_db_manage_id"
    upbit_api_to_db_manage_id = "upbit_api_to_db_manage_id"

    queue_dict = {
        to_upbit_api_manage_id: asyncio.Queue(),
        to_db_manage_id: asyncio.Queue(),
        upbit_api_to_db_manage_id: asyncio.Queue(),

        # rsi_to_trading_manage_id: asyncio.Queue(),
        # upbit_api_to_trading_manager_id: asyncio.Queue()
    }

    tasks = [
        # 업비트 API 를 통해 필요한 정보들을 받아오는 태스크
        asyncio.create_task(upbit_api_manage(queue_dict, to_upbit_api_manage_id, upbit_setting)),

        # DB를 관리하는 태스크
        asyncio.create_task(db_manage(
            queue_dict, to_db_manage_id, [to_upbit_api_manage_id, upbit_api_to_db_manage_id], "db/coinDB.db")),
        
        # 테스트 코드
        # asyncio.create_task(test_real_data()),
    ]

    # 실시간 데이터를 웹소켓을 통해 가져오는 태스크 + 실시간 데이터를 가공하는 태스크
    if program_setting["get_trade_from_ws"] or program_setting["get_orderbook_from_ws"]:
        # 관련 큐 추가
        db_to_real_data_manage_id = "db_to_real_data_manage_id"
        to_process_real_data_id = "to_process_real_data_id"
        queue_dict[db_to_real_data_manage_id] = asyncio.Queue()
        queue_dict[to_process_real_data_id] = asyncio.Queue()

        # 태스크 추가
        tasks.append(asyncio.create_task(get_real_data_manage(
            queue_dict, [to_db_manage_id, db_to_real_data_manage_id], to_process_real_data_id, program_setting
        )))
        tasks.append(asyncio.create_task(process_real_data_manage(
            queue_dict, to_process_real_data_id, to_db_manage_id, program_setting
        )))

    # REST API 로 종목들 과거 분봉 가져오는 태스크
    if program_setting["save_old_minute_price_to_db_with_rest_api"]:
        # 관련 큐 추가
        to_save_old_minute_price_id = "to_save_old_minute_price_id"
        queue_dict[to_save_old_minute_price_id] = asyncio.Queue()

        # 태스크 추가
        tasks.append(asyncio.create_task(
            save_old_minute_price(
                queue_dict, to_save_old_minute_price_id, to_upbit_api_manage_id, to_db_manage_id
            )
        ))

    # 자동 트레이딩 실행 태스크
    if program_setting['do_auto_trade']:
        # 관련 큐 추가
        to_do_auto_trade = 'to_do_auto_trade'
        queue_dict[to_do_auto_trade] = asyncio.Queue()
        upbit_api_to_trading_manager_id = "upbit_api_to_trading_manager_id"
        queue_dict[upbit_api_to_trading_manager_id] = asyncio.Queue()

        # RSI 관련 큐 추가
        to_get_rsi_id = 'to_get_rsi_id'
        queue_dict[to_get_rsi_id] = asyncio.Queue()

        # 태스크 추가
        tasks.append(asyncio.create_task(trading_manage(
            queue_dict, to_do_auto_trade, [upbit_api_to_trading_manager_id, to_upbit_api_manage_id],
            [to_get_rsi_id]
        )))

        # 전략 분석 태스크
        if program_setting['analyze_old_minute_price_with_strategy']:
            # 관련 큐 추가
            to_analyze_old_data_with_strategy_id = 'to_analyze_old_data_with_strategy_id'
            queue_dict[to_analyze_old_data_with_strategy_id] = asyncio.Queue()

            # 태스크 추가
            if True:  # DB에 보조지표 저장하는 태스크
                tasks.append(asyncio.create_task(
                    save_old_data_with_strategy(
                        queue_dict, to_analyze_old_data_with_strategy_id, to_db_manage_id, to_do_auto_trade
                    )
                ))
            else:  # 그 외에는 DB 로부터 보조지표 가져와서 분석하는 태스크
                tasks.append(asyncio.create_task(
                    analyze_old_data_with_strategy(
                        queue_dict, to_analyze_old_data_with_strategy_id, to_db_manage_id, to_do_auto_trade
                    )
                ))

        # RSI 전략 계산 태스크
        if program_setting['get_rsi']:
            # 태스크 추가
            tasks.append(asyncio.create_task(
                calculate_rsi_date(queue_dict, to_get_rsi_id, to_upbit_api_manage_id, to_do_auto_trade)))

    for t in tasks:
        await t


async def process_real_data_manage(queue_dict, to_process_real_data_id, to_db_manage_id, program_setting):
    write_trade_orderbook_to_db = program_setting["write_trade_orderbook_to_db"]
    min_ohlc_by_code = {}
    start_date = str(datetime.date.today())
    while True:
        data = await queue_dict[to_process_real_data_id].get()

        ty = data['ty']

        # 체결(Trade) 응답
        # 참고: https://docs.upbit.com/docs/upbit-quotation-websocket#%EC%B2%B4%EA%B2%B0trade-%EC%9D%91%EB%8B%B5
        if ty == 'trade':
            cd, td, ttm, tp, tv, sid = data['cd'], data['td'], data['ttm'], data['tp'], data['tv'], data['sid']
            tms = data['tms']

            # db 에 저장 요청 전송
            if write_trade_orderbook_to_db:
                queue_dict[to_db_manage_id].put_nowait({
                    'code': 'save_db', 'response_id': None,
                    'ty': ty, 'cd': cd, 'td': td, 'ttm': ttm, 'sid': sid, 'tp': tp, 'tv': tv, 'tms': tms
                })

        # 호가(Orderbook) 응답
        # 참고: https://docs.upbit.com/docs/upbit-quotation-websocket#%ED%98%B8%EA%B0%80orderbook-%EC%9D%91%EB%8B%B5
        elif ty == 'orderbook':
            cd, td, tas, tbs, obu = data['cd'], start_date, data['tas'], data['tbs'], data['obu']
            tms = data['tms']

            # db 에 저장 요청 전송
            if write_trade_orderbook_to_db:
                queue_dict[to_db_manage_id].put_nowait({
                    'code': 'save_db', 'response_id': None,
                    'ty': ty, 'cd': cd, 'td': td, 'tas': tas, 'tbs': tbs, 'obu': obu, 'tms': tms
                })

        continue

        code = data['cd']
        trade_price = data['tp']
        trade_date = "".join(data['td'].split('-'))
        trade_time = "".join(data['ttm'].split(":"))

        if code not in min_ohlc_by_code.keys():
            min_ohlc_by_code[code] = {
                'start_date': trade_date,
                'start_time': trade_time[0:4],
                'min_ohlc': {}
            }

        cur_min_ohlc_by_code = min_ohlc_by_code[code]
        if trade_date == cur_min_ohlc_by_code['start_date'] \
                and trade_time[0:4] == cur_min_ohlc_by_code['start_time']:
            continue

        try:
            cur_datetime = trade_date + '-' + trade_time
            cur_min_ohlc = cur_min_ohlc_by_code['min_ohlc']
            if len(cur_min_ohlc) < 1 or cur_min_ohlc['datetime'][:13] != cur_datetime[:13]:
                # db에 저장하는 기능은 우선 비활성화
                # if len(cur_min_ohlc) > 0:
                #     save_to_test_db(code, cur_min_ohlc)
                if len(cur_min_ohlc) > 0:
                    queue2.put_nowait(
                        {'code': code, 'date_time': cur_min_ohlc['datetime'], 'ohlc': cur_min_ohlc['ohlc']})
                cur_min_ohlc_by_code['min_ohlc'] = \
                    {'datetime': cur_datetime[:13], 'ohlc': [trade_price, trade_price, trade_price, trade_price]}
                continue

            target = cur_min_ohlc['ohlc']

            # 종가/고가/저가 갱신
            target[3] = trade_price
            if target[1] < trade_price:
                target[1] = trade_price
            if target[2] > trade_price:
                target[2] = trade_price

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print(exc_tb.tb_lineno)
            print(e)
